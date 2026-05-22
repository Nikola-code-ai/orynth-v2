"""Phase 2 integration tests for ``swarm_server_node``.

Drives the five-drone orchestrator (takeoff -> engage formation -> land)
against five in-process fake MAVROS / FCU nodes — no live MAVROS or ArduPilot
SITL. Each fake records requests and simulates a vehicle that teleports to the
last commanded setpoint, so the server's parallel command fan-out, formation
control loop and frame handling are all exercised.
"""

import threading
import time

import pytest
import rclpy
from geometry_msgs.msg import Point, PoseStamped
from mavros_msgs.msg import PositionTarget, State
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from rclpy.executors import MultiThreadedExecutor
from sensor_msgs.msg import NavSatFix
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray
from std_srvs.srv import Trigger
from swarm_msgs.msg import SwarmStatus
from swarm_msgs.srv import FollowLeader, ManualGoto, SetFormation, SwarmTakeoff

from swarm_control.swarm_server_node import SwarmServer


class FakeFcu(Node):
    """Namespaced stand-in for one drone's MAVROS node plus its ArduPilot FCU."""

    def __init__(self, index: int) -> None:
        super().__init__(f"fake_fcu_{index}")
        ns = f"drone_{index}/mavros"
        self.index = index
        self.connected = True
        self.armed = False
        self.mode = "STABILIZE"
        self.pos = [0.0, 0.0, 0.0]
        self.setpoints: list = []
        # Phase 2.5a: switch off to simulate a leader-pose dropout.
        self.publish_pose = True

        self.create_service(CommandBool, f"{ns}/cmd/arming", self._on_arming)
        self.create_service(SetMode, f"{ns}/set_mode", self._on_set_mode)
        self.create_service(CommandTOL, f"{ns}/cmd/takeoff", self._on_takeoff)
        self.create_service(CommandTOL, f"{ns}/cmd/land", self._on_land)
        self.create_subscription(
            PositionTarget, f"{ns}/setpoint_raw/local", self._on_setpoint, 10
        )
        self._state_pub = self.create_publisher(State, f"{ns}/state", 10)
        self._pose_pub = self.create_publisher(
            PoseStamped, f"{ns}/local_position/pose", 10
        )
        self._navsat_pub = self.create_publisher(
            NavSatFix, f"{ns}/global_position/global", 10
        )
        self.create_timer(0.05, self._publish_telemetry)

    def _publish_telemetry(self) -> None:
        state = State()
        state.connected = self.connected
        state.armed = self.armed
        state.guided = self.mode == "GUIDED"
        state.mode = self.mode
        self._state_pub.publish(state)

        if self.publish_pose:
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.pose.position.x = self.pos[0]
            pose.pose.position.y = self.pos[1]
            pose.pose.position.z = self.pos[2]
            self._pose_pub.publish(pose)

        # All fakes share one GPS datum -> calibration yields ~zero offsets,
        # exercising the calibration path with field == local.
        fix = NavSatFix()
        fix.latitude = -35.363262
        fix.longitude = 149.165237
        fix.altitude = 584.0
        self._navsat_pub.publish(fix)

    def _on_arming(self, request, response):
        self.armed = bool(request.value)
        response.success = True
        return response

    def _on_set_mode(self, request, response):
        self.mode = request.custom_mode
        response.mode_sent = True
        return response

    def _on_takeoff(self, request, response):
        self.pos[2] = request.altitude  # instant climb
        response.success = True
        return response

    def _on_land(self, request, response):
        self.pos[2] = 0.0
        self.armed = False
        response.success = True
        return response

    def _on_setpoint(self, msg: PositionTarget) -> None:
        self.setpoints.append(msg)
        self.pos = [msg.position.x, msg.position.y, msg.position.z]


@pytest.fixture(scope="module", autouse=True)
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


@pytest.fixture
def swarm():
    """Bring up five fake FCUs + the swarm server under one executor."""
    fakes = [FakeFcu(i) for i in range(5)]
    server = SwarmServer()
    driver = Node("test_driver")

    executor = MultiThreadedExecutor(num_threads=16)
    for fake in fakes:
        executor.add_node(fake)
    executor.add_node(server)
    executor.add_node(driver)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    try:
        yield fakes, server, driver
    finally:
        executor.shutdown()
        spin_thread.join(timeout=5.0)
        server.shutdown()
        for node in (*fakes, server, driver):
            node.destroy_node()


def _call(driver: Node, srv_type, name: str, request, timeout_s: float = 60.0):
    """Blocking service call from the driver node; returns the response."""
    client = driver.create_client(srv_type, name)
    assert client.wait_for_service(timeout_sec=10.0), f"{name} never appeared"
    future = client.call_async(request)
    deadline = time.monotonic() + timeout_s
    while not future.done():
        if time.monotonic() > deadline:
            raise AssertionError(f"{name} timed out")
        time.sleep(0.02)
    return future.result()


def _wait_until(predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_takeoff_formation_land(swarm):
    fakes, _server, driver = swarm

    # ── Coordinated takeoff ──────────────────────────────────────────────
    req = SwarmTakeoff.Request()
    req.altitude_m = 5.0
    resp = _call(driver, SwarmTakeoff, "/swarm/takeoff", req)
    assert resp.success, resp.message
    assert all(f.armed for f in fakes)
    assert all(abs(f.pos[2] - 5.0) < 0.7 for f in fakes)

    # ── Engage a diamond and let the control loop converge ───────────────
    fr = SetFormation.Request()
    fr.formation_name = "diamond"
    fr.spacing_m = 3.0
    fr.heading_deg = 0.0
    resp = _call(driver, SetFormation, "/swarm/engage_formation", fr)
    assert resp.success, resp.message

    # Leader ref is (0,0,5); heading 0 -> diamond slots in field ENU.
    expected = {
        1: (-3.0, 3.0),  # left wing
        2: (-3.0, -3.0),  # right wing
        3: (-6.0, 0.0),  # tail
        4: (-3.0, 0.0),  # centre
    }

    def followers_in_slots() -> bool:
        return all(
            abs(fakes[i].pos[0] - ex) < 0.5 and abs(fakes[i].pos[1] - ey) < 0.5
            for i, (ex, ey) in expected.items()
        )

    assert _wait_until(followers_in_slots, timeout_s=5.0), (
        "followers did not converge to diamond slots: "
        + ", ".join(f"drone_{i}={fakes[i].pos}" for i in expected)
    )

    # ── Coordinated land ─────────────────────────────────────────────────
    resp = _call(driver, Trigger, "/swarm/land", Trigger.Request())
    assert resp.success, resp.message
    assert not any(f.armed for f in fakes)


def test_engage_formation_rejects_unknown_name(swarm):
    _fakes, _server, driver = swarm
    fr = SetFormation.Request()
    fr.formation_name = "wedge"
    fr.spacing_m = 3.0
    fr.heading_deg = 0.0
    resp = _call(driver, SetFormation, "/swarm/engage_formation", fr)
    assert not resp.success
    assert "unknown formation" in resp.message


def test_manual_goto_service_is_advertised(swarm):
    _fakes, _server, driver = swarm
    # Each drone exposes its own manual_goto endpoint.
    client = driver.create_client(ManualGoto, "/swarm/drone_2/manual_goto")
    assert client.wait_for_service(timeout_sec=10.0)
    req = ManualGoto.Request()
    req.target = Point(x=4.0, y=0.0, z=5.0)
    resp = _call(driver, ManualGoto, "/swarm/drone_2/manual_goto", req)
    assert resp.success, resp.message


# ── Phase 2.5a — leader-follow ──────────────────────────────────────────────
# Diamond slot offsets, leader-relative (forward, left) in spacing units. With
# heading 0 the forward axis is East and the left axis is North, so a
# follower's field target is leader_xy + (forward, left) * spacing.
_DIAMOND_OFFSETS = {1: (-1.0, 1.0), 2: (-1.0, -1.0), 3: (-2.0, 0.0), 4: (-1.0, 0.0)}


def _expected_followers(leader_xy, spacing):
    lx, ly = leader_xy
    return {
        i: (lx + fwd * spacing, ly + left * spacing)
        for i, (fwd, left) in _DIAMOND_OFFSETS.items()
    }


def _followers_settled(fakes, expected, tol: float = 0.5) -> bool:
    return all(
        abs(fakes[i].pos[0] - ex) < tol and abs(fakes[i].pos[1] - ey) < tol
        for i, (ex, ey) in expected.items()
    )


def _engage_follow(driver, formation: str = "diamond", spacing: float = 3.0):
    """Take the swarm off, then engage live leader-follow tracking."""
    req = SwarmTakeoff.Request()
    req.altitude_m = 5.0
    assert _call(driver, SwarmTakeoff, "/swarm/takeoff", req).success
    fl = FollowLeader.Request()
    fl.enable = True
    fl.formation_name = formation
    fl.spacing_m = spacing
    resp = _call(driver, FollowLeader, "/swarm/follow_leader", fl)
    assert resp.success, resp.message


def test_follow_leader_tracks_moving_leader(swarm):
    fakes, _server, driver = swarm
    _engage_follow(driver, "diamond", 3.0)

    # Followers form up around the leader's start pose (origin).
    start = _expected_followers((0.0, 0.0), 3.0)
    assert _wait_until(lambda: _followers_settled(fakes, start), 5.0), (
        "followers did not form up around the leader: "
        + ", ".join(f"drone_{i}={fakes[i].pos}" for i in start)
    )

    # The operator flies the leader; the followers must track its live pose.
    g = ManualGoto.Request()
    g.target = Point(x=12.0, y=0.0, z=5.0)
    assert _call(driver, ManualGoto, "/swarm/drone_0/manual_goto", g).success

    moved = _expected_followers((12.0, 0.0), 3.0)
    assert _wait_until(lambda: _followers_settled(fakes, moved), 6.0), (
        "followers did not track the leader to its new pose: "
        + ", ".join(f"drone_{i}={fakes[i].pos}" for i in moved)
    )
    # The leader is operator-flown — the follow loop never re-commands slot 0.
    assert abs(fakes[0].pos[0] - 12.0) < 0.5

    # Disengaging returns the swarm to a plain airborne hold.
    off = FollowLeader.Request()
    off.enable = False
    resp = _call(driver, FollowLeader, "/swarm/follow_leader", off)
    assert resp.success and "disengaged" in resp.message


def test_follow_leader_watchdog_holds_then_recovers(swarm):
    fakes, _server, driver = swarm
    _engage_follow(driver, "diamond", 3.0)

    expected = _expected_followers((0.0, 0.0), 3.0)
    assert _wait_until(lambda: _followers_settled(fakes, expected), 5.0)
    held = {i: list(fakes[i].pos) for i in expected}

    statuses: list = []
    driver.create_subscription(
        SwarmStatus, "/swarm/status", lambda m: statuses.append(m), 5
    )

    # Dropout: the leader stops publishing pose. The watchdog must latch the
    # emergency and the followers must hold their last formation slots.
    fakes[0].publish_pose = False
    assert _wait_until(
        lambda: statuses and statuses[-1].emergency, 6.0
    ), "watchdog did not raise the leader-pose-stale emergency"
    for i, p in held.items():
        assert abs(fakes[i].pos[0] - p[0]) < 0.6
        assert abs(fakes[i].pos[1] - p[1]) < 0.6

    # Recovery: pose resumes, the watchdog clears the emergency.
    fakes[0].publish_pose = True
    assert _wait_until(
        lambda: statuses and not statuses[-1].emergency, 6.0
    ), "watchdog did not clear after the leader pose recovered"


def test_follow_leader_rejects_unknown_formation(swarm):
    _fakes, _server, driver = swarm
    fl = FollowLeader.Request()
    fl.enable = True
    fl.formation_name = "spiral"
    fl.spacing_m = 3.0
    resp = _call(driver, FollowLeader, "/swarm/follow_leader", fl)
    assert not resp.success
    assert "unknown formation" in resp.message


def test_formation_error_topic_reports_low_drift(swarm):
    fakes, _server, driver = swarm
    errors: list = []
    driver.create_subscription(
        Float32MultiArray, "/swarm/formation_error", errors.append, 5
    )
    _engage_follow(driver, "diamond", 3.0)

    expected = _expected_followers((0.0, 0.0), 3.0)
    assert _wait_until(lambda: _followers_settled(fakes, expected), 5.0)

    # Once the followers settle, the published per-follower error is small;
    # the leader slot (index 0) always reads 0.0.
    def reports_low_drift() -> bool:
        if not errors:
            return False
        data = errors[-1].data
        return (
            len(data) == 5
            and data[0] == 0.0
            and all(data[i] < 0.5 for i in (1, 2, 3, 4))
        )

    assert _wait_until(reports_low_drift, 5.0), (
        "/swarm/formation_error never reported low follower drift: "
        f"{list(errors[-1].data) if errors else None}"
    )
