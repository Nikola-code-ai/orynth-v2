"""Phase 1 unit tests for ``MavrosAdapter``.

Exercises the adapter's full command path (connect, GUIDED, arm, takeoff,
waypoint, land) against an in-process fake MAVROS node — no live MAVROS or
ArduPilot SITL required. The fake records every request and simulates the
vehicle so the adapter's request construction, response handling, setpoint
streaming and pose-tracking logic are all covered.
"""

import math
import threading
import time

import pytest
import rclpy
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import PositionTarget, State
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from rclpy.executors import MultiThreadedExecutor
from rclpy.logging import get_logger
from rclpy.node import Node

from swarm_control.mavros_adapter import MavrosAdapter
from swarm_control.sitl_mission import run_mission
from swarm_control.swarm_api import (
    FollowReferenceRequest,
    LandRequest,
    MotionTarget,
    PlatformProfile,
    TakeoffRequest,
)


class FakeMavros(Node):
    """In-process stand-in for the MAVROS node plus an ArduPilot FCU."""

    def __init__(self) -> None:
        super().__init__("fake_mavros")
        # Simulated vehicle state.
        self.connected = True
        self.armed = False
        self.mode = "STABILIZE"
        self.pos = [0.0, 0.0, 0.0]
        # Recorded requests, for assertions.
        self.arming_requests: list = []
        self.set_mode_requests: list = []
        self.takeoff_requests: list = []
        self.land_requests: list = []
        self.setpoints: list = []
        # Leader-follow test knobs (Phase 2.5a): yaw the published pose
        # carries, and a switch to simulate a pose dropout for the watchdog.
        self.yaw = 0.0
        self.publish_pose = True

        self.create_service(CommandBool, "mavros/cmd/arming", self._on_arming)
        self.create_service(SetMode, "mavros/set_mode", self._on_set_mode)
        self.create_service(CommandTOL, "mavros/cmd/takeoff", self._on_takeoff)
        self.create_service(CommandTOL, "mavros/cmd/land", self._on_land)
        self.create_subscription(
            PositionTarget, "mavros/setpoint_raw/local", self._on_setpoint, 10
        )
        self._state_pub = self.create_publisher(State, "mavros/state", 10)
        self._pose_pub = self.create_publisher(
            PoseStamped, "mavros/local_position/pose", 10
        )
        self.create_timer(0.05, self._publish_telemetry)

    def _publish_telemetry(self) -> None:
        state = State()
        state.connected = self.connected
        state.armed = self.armed
        state.guided = self.mode == "GUIDED"
        state.mode = self.mode
        self._state_pub.publish(state)

        if not self.publish_pose:
            return  # simulate a pose dropout — see the watchdog test

        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.pose.position.x = self.pos[0]
        pose.pose.position.y = self.pos[1]
        pose.pose.position.z = self.pos[2]
        pose.pose.orientation.z = math.sin(self.yaw / 2.0)
        pose.pose.orientation.w = math.cos(self.yaw / 2.0)
        self._pose_pub.publish(pose)

    def _on_arming(self, request, response):
        self.arming_requests.append(request)
        self.armed = bool(request.value)
        response.success = True
        return response

    def _on_set_mode(self, request, response):
        self.set_mode_requests.append(request)
        self.mode = request.custom_mode
        response.mode_sent = True
        return response

    def _on_takeoff(self, request, response):
        self.takeoff_requests.append(request)
        self.pos[2] = request.altitude  # simulate an instant climb
        response.success = True
        return response

    def _on_land(self, request, response):
        self.land_requests.append(request)
        self.pos[2] = 0.0
        self.armed = False
        response.success = True
        return response

    def _on_setpoint(self, msg: PositionTarget) -> None:
        self.setpoints.append(msg)
        # Simulate instant travel to the commanded position.
        self.pos = [msg.position.x, msg.position.y, msg.position.z]


@pytest.fixture(scope="module", autouse=True)
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


@pytest.fixture
def harness():
    """Spin a fake MAVROS node + an adapter under one background executor."""
    fake = FakeMavros()
    driver = Node("test_driver")
    adapter = MavrosAdapter(driver, vehicle_id="drone_0")

    executor = MultiThreadedExecutor()
    executor.add_node(fake)
    executor.add_node(driver)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    try:
        yield adapter, fake
    finally:
        executor.shutdown()
        spin_thread.join(timeout=5.0)
        driver.destroy_node()
        fake.destroy_node()


def test_wait_for_connection(harness):
    adapter, _ = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    assert adapter.connected


def test_platform_profile_and_id(harness):
    adapter, _ = harness
    assert adapter.platform_profile is PlatformProfile.ARDUPILOT_SITL
    assert adapter.vehicle_id == "drone_0"


def test_enable_external_control_sets_guided(harness):
    adapter, fake = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    assert adapter.enable_external_control()
    assert fake.set_mode_requests[-1].custom_mode == "GUIDED"
    assert fake.mode == "GUIDED"


def test_arm(harness):
    adapter, fake = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    assert adapter.arm()
    assert fake.arming_requests[-1].value is True
    assert adapter.armed


def test_takeoff_reaches_altitude(harness):
    adapter, fake = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    assert adapter.takeoff(TakeoffRequest(height_m=5.0, speed_mps=1.0))
    assert fake.takeoff_requests[-1].altitude == pytest.approx(5.0)


def test_go_to_streams_setpoints_and_arrives(harness):
    adapter, fake = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    assert adapter.go_to(MotionTarget(point=(10.0, 0.0, 5.0), speed_mps=2.0))
    assert fake.setpoints, "expected at least one setpoint to be published"
    last = fake.setpoints[-1]
    assert last.coordinate_frame == PositionTarget.FRAME_LOCAL_NED
    assert last.type_mask == MavrosAdapter.POSITION_TYPE_MASK
    assert last.position.x == pytest.approx(10.0)
    assert last.position.z == pytest.approx(5.0)


def test_cancel_motion(harness):
    adapter, _ = harness
    assert adapter.cancel_motion() is True


def test_land_disarms(harness):
    adapter, fake = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    assert adapter.arm()
    assert adapter.land(LandRequest(speed_mps=0.5))
    assert len(fake.land_requests) == 1
    assert not adapter.armed


def test_hold_reference_streams_a_setpoint(harness):
    adapter, fake = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    req = FollowReferenceRequest(
        x=3.0,
        y=4.0,
        z=5.0,
        frame_id="map",
        speed_x_mps=0.0,
        speed_y_mps=0.0,
        speed_z_mps=0.0,
    )
    # Non-blocking: one PositionTarget published per call. A moving reference
    # is tracked by streaming the call (the swarm server's formation loop) —
    # stream it here too, which also lets pub/sub discovery settle.
    deadline = time.monotonic() + 5.0
    while not fake.setpoints and time.monotonic() < deadline:
        assert adapter.hold_reference(req) is True
        time.sleep(0.05)
    assert fake.setpoints, "hold_reference must publish a PositionTarget"
    last = fake.setpoints[-1]
    assert last.coordinate_frame == PositionTarget.FRAME_LOCAL_NED
    assert last.type_mask == MavrosAdapter.POSITION_TYPE_MASK
    assert last.position.x == pytest.approx(3.0)
    assert last.position.y == pytest.approx(4.0)
    assert last.position.z == pytest.approx(5.0)


def _wait(predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_pose_age_is_fresh_while_streaming(harness):
    """pose_age_s stays small while the FCU streams pose (Phase 2.5a)."""
    adapter, _fake = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    assert _wait(lambda: adapter.local_position is not None, 5.0)
    assert adapter.pose_age_s < 1.0


def test_pose_age_grows_on_dropout(harness):
    """pose_age_s climbs past the watchdog horizon once pose stops arriving."""
    adapter, fake = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    assert _wait(lambda: adapter.pose_age_s < 1.0, 5.0)
    fake.publish_pose = False  # simulate a leader-pose dropout
    assert _wait(
        lambda: adapter.pose_age_s > 1.5, 4.0
    ), "pose_age_s did not grow after the FCU stopped publishing pose"


def test_heading_rad_from_pose_quaternion(harness):
    """heading_rad decodes ENU yaw from the pose orientation quaternion."""
    adapter, fake = harness
    assert adapter.wait_for_connection(timeout_s=5.0)
    fake.yaw = math.pi / 2.0  # face North
    assert _wait(
        lambda: abs(adapter.heading_rad - math.pi / 2.0) < 1e-3, 5.0
    ), f"heading_rad never reached pi/2 (got {adapter.heading_rad})"


def test_full_mission_sequence(harness):
    adapter, fake = harness
    assert run_mission(adapter, get_logger("test_mission"))
    assert len(fake.takeoff_requests) == 1
    assert len(fake.land_requests) == 1
    assert fake.armed is False  # landed and disarmed at mission end


def test_close_is_safe(harness):
    adapter, _ = harness
    adapter.close()  # releasing entities must not raise
