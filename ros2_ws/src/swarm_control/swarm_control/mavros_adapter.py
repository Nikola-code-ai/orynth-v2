"""MAVROS-backed ``VehicleAdapter`` — the v1->v2 lynchpin (PLAN section I, #4).

Implements the backend-neutral ``VehicleAdapter`` contract against the MAVROS
service / topic surface of an ArduPilot Copter (SITL or hardware). All
ArduPilot integration is funnelled through this module (ADR 0002): no MAVLink
concept leaks above the adapter boundary.

The adapter wraps an externally-owned ``rclpy`` node and never spins it — the
caller runs an executor (see ``sitl_mission.py``). Every control method is
synchronous and blocking; service requests are issued with ``call_async`` and
the future polled while the caller's executor processes the graph.
"""

from __future__ import annotations

import math
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import PositionTarget, State
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from rclpy.callback_groups import CallbackGroup
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)

from .swarm_api import (
    FollowReferenceRequest,
    LandRequest,
    MotionTarget,
    PlatformProfile,
    TakeoffRequest,
)
from .vehicle_adapter import VehicleAdapter


class MavrosAdapter(VehicleAdapter):
    """Drive a single ArduPilot vehicle through its MAVROS interface."""

    #: ArduPilot Copter custom flight mode used for external (offboard) control.
    GUIDED_MODE = "GUIDED"

    #: PositionTarget type mask: command position only, ignore everything else.
    POSITION_TYPE_MASK = (
        PositionTarget.IGNORE_VX
        | PositionTarget.IGNORE_VY
        | PositionTarget.IGNORE_VZ
        | PositionTarget.IGNORE_AFX
        | PositionTarget.IGNORE_AFY
        | PositionTarget.IGNORE_AFZ
        | PositionTarget.IGNORE_YAW
        | PositionTarget.IGNORE_YAW_RATE
    )

    def __init__(
        self,
        node: Node,
        vehicle_id: str = "drone_0",
        *,
        mavros_ns: str = "mavros",
        profile: PlatformProfile = PlatformProfile.ARDUPILOT_SITL,
        service_timeout_s: float = 30.0,
        callback_group: CallbackGroup | None = None,
    ) -> None:
        self._node = node
        self._vehicle_id = vehicle_id
        self._profile = profile
        self._log = node.get_logger()

        # Timeouts and tolerances. ArduPilot SITL needs tens of seconds for
        # GPS / EKF to converge before pre-arm checks pass, hence the generous
        # arm budget.
        self._service_timeout_s = service_timeout_s
        self._mode_confirm_timeout_s = 15.0
        self._arm_timeout_s = 120.0
        self._arm_retry_period_s = 3.0
        self._arm_confirm_timeout_s = 10.0
        self._takeoff_timeout_s = 60.0
        self._goto_timeout_s = 90.0
        self._land_timeout_s = 90.0
        self._altitude_tol_m = 0.7
        self._goto_tol_m = 1.0
        self._setpoint_period_s = 0.1

        self._state: State | None = None
        self._pose: PoseStamped | None = None
        self._global: NavSatFix | None = None
        self._goto_active = False

        ns = mavros_ns.strip("/")
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        # A shared callback group lets a MultiThreadedExecutor service many
        # adapters (and their blocking calls) concurrently — the swarm server
        # passes a ReentrantCallbackGroup. None keeps Phase 1 behaviour.
        cbg = callback_group
        self._state_sub = node.create_subscription(
            State, f"{ns}/state", self._on_state, sensor_qos, callback_group=cbg
        )
        self._pose_sub = node.create_subscription(
            PoseStamped,
            f"{ns}/local_position/pose",
            self._on_pose,
            sensor_qos,
            callback_group=cbg,
        )
        self._global_sub = node.create_subscription(
            NavSatFix,
            f"{ns}/global_position/global",
            self._on_global,
            sensor_qos,
            callback_group=cbg,
        )
        self._setpoint_pub = node.create_publisher(
            PositionTarget, f"{ns}/setpoint_raw/local", 10
        )
        self._arm_client = node.create_client(
            CommandBool, f"{ns}/cmd/arming", callback_group=cbg
        )
        self._mode_client = node.create_client(
            SetMode, f"{ns}/set_mode", callback_group=cbg
        )
        self._takeoff_client = node.create_client(
            CommandTOL, f"{ns}/cmd/takeoff", callback_group=cbg
        )
        self._land_client = node.create_client(
            CommandTOL, f"{ns}/cmd/land", callback_group=cbg
        )
        self._log.info(
            f"MavrosAdapter[{vehicle_id}] bound to /{ns} ({profile.value})"
        )

    # ── VehicleAdapter identity ─────────────────────────────────────────────
    @property
    def vehicle_id(self) -> str:
        return self._vehicle_id

    @property
    def platform_profile(self) -> PlatformProfile:
        return self._profile

    # ── Live telemetry (read-only, updated by the executor thread) ──────────
    @property
    def connected(self) -> bool:
        """True once MAVROS reports an FCU heartbeat."""
        return self._state is not None and self._state.connected

    @property
    def armed(self) -> bool:
        """True while the FCU reports the vehicle armed."""
        return self._state is not None and self._state.armed

    @property
    def mode(self) -> str:
        """Current FCU flight-mode string (empty until first /mavros/state)."""
        return self._state.mode if self._state is not None else ""

    @property
    def local_position(self) -> tuple[float, float, float] | None:
        """Last known local ENU position ``(x, y, z)`` in metres, or None."""
        pose = self._pose
        if pose is None:
            return None
        p = pose.pose.position
        return (p.x, p.y, p.z)

    @property
    def global_position(self) -> tuple[float, float, float] | None:
        """Last known global fix ``(lat_deg, lon_deg, alt_m)``, or None.

        The swarm server uses this to calibrate each drone's offset within a
        shared field frame — drones in independent EKF frames are otherwise
        not directly comparable.
        """
        fix = self._global
        if fix is None:
            return None
        return (fix.latitude, fix.longitude, fix.altitude)

    # ── VehicleAdapter operations ───────────────────────────────────────────
    def wait_for_connection(self, timeout_s: float = 60.0) -> bool:
        """Block until MAVROS reports an FCU connection."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.connected:
                self._log.info("FCU connection up")
                return True
            time.sleep(0.2)
        self._log.error("no FCU connection (/mavros/state) within timeout")
        return False

    def arm(self) -> bool:
        """Arm the vehicle, retrying until ArduPilot pre-arm checks pass.

        Returns only once /mavros/state confirms ``armed`` — a successful
        CommandBool response alone is not treated as armed.
        """
        deadline = time.monotonic() + self._arm_timeout_s
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            request = CommandBool.Request()
            request.value = True
            resp = self._call(self._arm_client, request, f"arm (attempt {attempt})")
            if resp is not None and resp.success:
                confirm_deadline = time.monotonic() + self._arm_confirm_timeout_s
                while time.monotonic() < confirm_deadline:
                    if self.armed:
                        self._log.info("vehicle armed")
                        return True
                    time.sleep(0.1)
            # Pre-arm checks (GPS / EKF) may still be converging — retry.
            time.sleep(self._arm_retry_period_s)
        self._log.error("arm failed: not armed within timeout")
        return False

    def enable_external_control(self) -> bool:
        """Switch the FCU into GUIDED mode and confirm the transition."""
        request = SetMode.Request()
        request.base_mode = 0
        request.custom_mode = self.GUIDED_MODE
        resp = self._call(self._mode_client, request, "set GUIDED mode")
        if resp is None or not resp.mode_sent:
            self._log.error("set-mode request was not accepted")
            return False
        deadline = time.monotonic() + self._mode_confirm_timeout_s
        while time.monotonic() < deadline:
            if self._state is not None and self._state.mode == self.GUIDED_MODE:
                self._log.info("GUIDED mode active")
                return True
            time.sleep(0.1)
        self._log.error("GUIDED mode not confirmed within timeout")
        return False

    def takeoff(self, request: TakeoffRequest) -> bool:
        """Command a GUIDED takeoff and block until the altitude is reached."""
        cmd = CommandTOL.Request()
        cmd.min_pitch = 0.0
        cmd.yaw = 0.0
        cmd.latitude = 0.0
        cmd.longitude = 0.0
        cmd.altitude = float(request.height_m)
        resp = self._call(self._takeoff_client, cmd, "takeoff")
        if resp is None or not resp.success:
            self._log.error("takeoff command rejected")
            return False
        return self._wait_for_altitude(request.height_m, self._takeoff_timeout_s)

    def go_to(self, target: MotionTarget) -> bool:
        """Fly to ``target.point`` by streaming local position setpoints."""
        x, y, z = (float(c) for c in target.point)
        self._goto_active = True
        deadline = time.monotonic() + self._goto_timeout_s
        while time.monotonic() < deadline:
            if not self._goto_active:
                self._log.warning("go_to cancelled before arrival")
                return False
            self._publish_setpoint(x, y, z)
            if self._distance_to(x, y, z) <= self._goto_tol_m:
                self._goto_active = False
                self._log.info(f"reached waypoint ({x:.1f}, {y:.1f}, {z:.1f})")
                return True
            time.sleep(self._setpoint_period_s)
        self._goto_active = False
        self._log.error("waypoint not reached within timeout")
        return False

    def hold_reference(self, request: FollowReferenceRequest) -> bool:
        """Publish one formation-hold setpoint at the reference point.

        Non-blocking by design: ArduPilot GUIDED tracks the most recent
        position target, so a *moving* reference is followed by streaming this
        call at a fixed rate (the swarm server's formation loop does exactly
        that). The vehicle must already be in GUIDED — see
        ``enable_external_control``. Returns True once the setpoint is queued
        for publication.
        """
        self._publish_setpoint(
            float(request.x), float(request.y), float(request.z)
        )
        return True

    def cancel_motion(self) -> bool:
        """Stop an in-progress ``go_to``. Best-effort; always returns True."""
        self._goto_active = False
        return True

    def land(self, request: LandRequest) -> bool:
        """Command a landing and block until the FCU reports disarmed."""
        cmd = CommandTOL.Request()
        cmd.min_pitch = 0.0
        cmd.yaw = 0.0
        cmd.latitude = 0.0
        cmd.longitude = 0.0
        cmd.altitude = 0.0
        resp = self._call(self._land_client, cmd, "land")
        if resp is None or not resp.success:
            self._log.error("land command rejected")
            return False
        # ArduPilot disarms automatically once it settles on the ground.
        deadline = time.monotonic() + self._land_timeout_s
        while time.monotonic() < deadline:
            if self._state is not None and not self._state.armed:
                self._log.info("landed and disarmed")
                return True
            time.sleep(0.5)
        self._log.error("disarm not confirmed after land within timeout")
        return False

    def close(self) -> None:
        """Release every ROS entity this adapter created on the node."""
        self._goto_active = False
        destructors = (
            (self._node.destroy_publisher, self._setpoint_pub),
            (self._node.destroy_subscription, self._state_sub),
            (self._node.destroy_subscription, self._pose_sub),
            (self._node.destroy_subscription, self._global_sub),
            (self._node.destroy_client, self._arm_client),
            (self._node.destroy_client, self._mode_client),
            (self._node.destroy_client, self._takeoff_client),
            (self._node.destroy_client, self._land_client),
        )
        for destroy, entity in destructors:
            try:
                destroy(entity)
            except Exception:  # best-effort teardown
                pass

    # ── Internal helpers ────────────────────────────────────────────────────
    def _on_state(self, msg: State) -> None:
        self._state = msg

    def _on_pose(self, msg: PoseStamped) -> None:
        self._pose = msg

    def _on_global(self, msg: NavSatFix) -> None:
        self._global = msg

    def _distance_to(self, x: float, y: float, z: float) -> float:
        """Euclidean distance from the last known pose to ``(x, y, z)``."""
        pose = self._pose
        if pose is None:
            return math.inf
        p = pose.pose.position
        return math.sqrt((p.x - x) ** 2 + (p.y - y) ** 2 + (p.z - z) ** 2)

    def _wait_for_altitude(self, target_m: float, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            pose = self._pose
            if pose is not None:
                error = abs(pose.pose.position.z - target_m)
                if error <= self._altitude_tol_m:
                    self._log.info(f"reached altitude {target_m:.1f} m")
                    return True
            time.sleep(0.2)
        self._log.error(f"altitude {target_m:.1f} m not reached within timeout")
        return False

    def _publish_setpoint(self, x: float, y: float, z: float) -> None:
        msg = PositionTarget()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.coordinate_frame = PositionTarget.FRAME_LOCAL_NED
        msg.type_mask = self.POSITION_TYPE_MASK
        msg.position.x = x
        msg.position.y = y
        msg.position.z = z
        self._setpoint_pub.publish(msg)

    def _call(self, client, request, what: str):
        """Issue a blocking service call; return the response or None."""
        if not client.wait_for_service(timeout_sec=self._service_timeout_s):
            self._log.error(f"{what}: service {client.srv_name} unavailable")
            return None
        future = client.call_async(request)
        deadline = time.monotonic() + self._service_timeout_s
        while rclpy.ok() and not future.done():
            if time.monotonic() > deadline:
                self._log.error(f"{what}: service call timed out")
                return None
            time.sleep(0.02)
        return future.result()
