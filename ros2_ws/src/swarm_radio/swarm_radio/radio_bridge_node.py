"""``radio_bridge`` ROS 2 node — Orynth inter-drone radio link (ADR 0009).

Runs in one of two roles, selected at launch by the ``role`` parameter:

* ``leader`` — bridges every *follower* drone's MAVROS surface onto the radio:

    - **Inbound** ``ORYNTH_DRONE_STATE`` from a follower is republished locally
      as if it had come from a real MAVROS for that drone (``/drone_K/mavros/
      state``, ``local_position/pose``, ``global_position/global``). This is
      the trick that lets ``swarm_server``'s ``MavrosAdapter`` instances run
      unchanged: each adapter sees a topic surface indistinguishable from a
      real MAVROS over the wire.
    - **Outbound** position setpoints written by ``swarm_server`` to
      ``/drone_K/mavros/setpoint_raw/local`` are picked up here and shipped as
      ``ORYNTH_SETPOINT``.
    - The four MAVROS command services (``arming``, ``set_mode``,
      ``cmd/takeoff``, ``cmd/land``) are *advertised* by this node under each
      follower's namespace; service calls turn into ``ORYNTH_COMMAND`` packets
      and block waiting for the matching ``ORYNTH_ACK``.

* ``follower`` — the inverse: listens on its local real MAVROS topics and
  republishes them over the radio; receives setpoints/commands from the
  leader and replays them onto its own MAVROS.

Watchdogs:
  * ``radio_link_age_s`` topic (Float32) publishes the age of the most recent
    frame from *any* peer. The local FC failsafe should be configured to
    handle ``BRAKE`` on radio loss; this node also commands ``BRAKE`` itself
    after ``radio_loss_brake_s`` seconds of silence and ``DISARM`` after
    ``radio_loss_disarm_s`` (follower role only — leader stays in control of
    its own airframe via the local FC).
"""

from __future__ import annotations

import math
import os
import threading
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import PositionTarget, State
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import Float32

from .radio_link import (
    Ack,
    BROADCAST_DRONE_ID,
    Command,
    DroneState,
    Heartbeat,
    LoopbackTransport,
    RadioLink,
    Setpoint,
    SerialTransport,
)

# Command enum mirror — kept here too so callers don't need to import dialect.
CMD_NOOP = 0
CMD_ARM = 1
CMD_DISARM = 2
CMD_TAKEOFF = 3
CMD_LAND = 4
CMD_ABORT = 5
CMD_SET_MODE_GUIDED = 6
CMD_SET_MODE_BRAKE = 7

ROLE_LEADER = 0
ROLE_FOLLOWER = 1


def _sensor_qos() -> QoSProfile:
    return QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
    )


class RadioBridgeNode(Node):
    """Bidirectional ROS 2 ↔ Orynth-MAVLink-radio bridge."""

    def __init__(self, link: RadioLink | None = None) -> None:
        super().__init__("radio_bridge")

        # ── parameters ────────────────────────────────────────────────────
        self.declare_parameter("role", os.environ.get("RADIO_ROLE", "follower"))
        self.declare_parameter("local_drone_id", int(os.environ.get("DRONE_ID", "0")))
        self.declare_parameter("drone_count", int(os.environ.get("DRONE_COUNT", "2")))
        self.declare_parameter("serial_device", os.environ.get("RADIO_DEVICE", "/dev/ttyUSB_RFD"))
        self.declare_parameter("serial_baud", int(os.environ.get("RADIO_BAUD", "57600")))
        self.declare_parameter("state_rate_hz", 10.0)
        self.declare_parameter("heartbeat_rate_hz", 2.0)
        self.declare_parameter("radio_loss_brake_s", 2.0)
        self.declare_parameter("radio_loss_disarm_s", 10.0)
        self.declare_parameter("command_ack_timeout_s", 3.0)

        self._role = str(self.get_parameter("role").value).lower()
        self._local_id = int(self.get_parameter("local_drone_id").value)
        self._drone_count = int(self.get_parameter("drone_count").value)
        self._state_period = 1.0 / float(self.get_parameter("state_rate_hz").value)
        self._hb_period = 1.0 / float(self.get_parameter("heartbeat_rate_hz").value)
        self._brake_after_s = float(self.get_parameter("radio_loss_brake_s").value)
        self._disarm_after_s = float(self.get_parameter("radio_loss_disarm_s").value)
        self._ack_timeout = float(self.get_parameter("command_ack_timeout_s").value)

        # ── radio link ────────────────────────────────────────────────────
        self._cbg = ReentrantCallbackGroup()
        if link is not None:
            self._link = link
        else:
            device = str(self.get_parameter("serial_device").value)
            baud = int(self.get_parameter("serial_baud").value)
            self._link = RadioLink(
                SerialTransport(device, baud=baud),
                local_drone_id=self._local_id,
            )
            self.get_logger().info(
                f"radio link open: {device} @ {baud} drone_id={self._local_id}"
            )

        # ── shared state ──────────────────────────────────────────────────
        self._t0 = time.monotonic()
        self._tx_cmd_seq = 0
        self._pending_acks: dict[int, "_PendingAck"] = {}
        self._pending_lock = threading.Lock()
        self._link_age_pub = self.create_publisher(Float32, "/radio/link_age_s", 5)
        self._last_brake_action: float = 0.0

        if self._role == "leader":
            self._init_leader()
        elif self._role == "follower":
            self._init_follower()
        else:
            raise ValueError(f"invalid role: {self._role!r} (expected leader|follower)")

        # ── timers ────────────────────────────────────────────────────────
        self.create_timer(0.02, self._poll_radio, callback_group=self._cbg)
        self.create_timer(self._hb_period, self._send_heartbeat, callback_group=self._cbg)
        self.create_timer(0.5, self._publish_link_age, callback_group=self._cbg)
        self.create_timer(1.0, self._watchdog_tick, callback_group=self._cbg)
        if self._role == "follower":
            self.create_timer(
                self._state_period, self._publish_drone_state, callback_group=self._cbg
            )

        self.get_logger().info(
            f"radio_bridge ready: role={self._role} local_id={self._local_id} "
            f"drone_count={self._drone_count}"
        )

    # ──────────────────────────────────────────────────────────────────────
    # Leader role: synthesize MAVROS surface for every remote drone
    # ──────────────────────────────────────────────────────────────────────
    def _init_leader(self) -> None:
        self._remote_ids = [i for i in range(self._drone_count) if i != self._local_id]
        self._remote_state_pubs: dict[int, dict] = {}

        for drone_id in self._remote_ids:
            ns = f"/drone_{drone_id}/mavros"
            pubs = {
                "state": self.create_publisher(State, f"{ns}/state", _sensor_qos()),
                "pose": self.create_publisher(PoseStamped, f"{ns}/local_position/pose", _sensor_qos()),
                "fix": self.create_publisher(NavSatFix, f"{ns}/global_position/global", _sensor_qos()),
            }
            self._remote_state_pubs[drone_id] = pubs

            # Forward setpoints written by swarm_server to the radio.
            self.create_subscription(
                PositionTarget,
                f"{ns}/setpoint_raw/local",
                self._make_setpoint_cb(drone_id),
                _sensor_qos(),
                callback_group=self._cbg,
            )

            # Mock MAVROS command services. MavrosAdapter calls these.
            self.create_service(
                CommandBool,
                f"{ns}/cmd/arming",
                self._make_arming_srv(drone_id),
                callback_group=self._cbg,
            )
            self.create_service(
                SetMode,
                f"{ns}/set_mode",
                self._make_set_mode_srv(drone_id),
                callback_group=self._cbg,
            )
            self.create_service(
                CommandTOL,
                f"{ns}/cmd/takeoff",
                self._make_takeoff_srv(drone_id),
                callback_group=self._cbg,
            )
            self.create_service(
                CommandTOL,
                f"{ns}/cmd/land",
                self._make_land_srv(drone_id),
                callback_group=self._cbg,
            )

    def _make_setpoint_cb(self, drone_id: int):
        def cb(msg: PositionTarget) -> None:
            # PositionTarget.position is in the frame on `coordinate_frame`. We
            # forward raw (x, y, z) — the follower replays it into MAVROS using
            # the same frame, so no transform is needed here.
            self._link.send_setpoint(
                Setpoint(
                    time_boot_ms=self._link.boot_ms(),
                    drone_id=drone_id,
                    x=msg.position.x,
                    y=msg.position.y,
                    z=msg.position.z,
                    yaw_rad=msg.yaw,
                    reference_age_ms=0,
                )
            )
        return cb

    def _make_arming_srv(self, drone_id: int):
        def handler(req: CommandBool.Request, resp: CommandBool.Response):
            ok, _ = self._issue_command(
                drone_id, CMD_ARM if req.value else CMD_DISARM, 0.0
            )
            resp.success = ok
            resp.result = 0 if ok else 4  # 0=ACCEPTED, 4=FAILED
            return resp
        return handler

    def _make_set_mode_srv(self, drone_id: int):
        def handler(req: SetMode.Request, resp: SetMode.Response):
            mode = (req.custom_mode or "").upper()
            cmd_id = {
                "GUIDED": CMD_SET_MODE_GUIDED,
                "BRAKE": CMD_SET_MODE_BRAKE,
            }.get(mode, CMD_NOOP)
            if cmd_id == CMD_NOOP:
                resp.mode_sent = False
                return resp
            ok, _ = self._issue_command(drone_id, cmd_id, 0.0)
            resp.mode_sent = ok
            return resp
        return handler

    def _make_takeoff_srv(self, drone_id: int):
        def handler(req: CommandTOL.Request, resp: CommandTOL.Response):
            ok, _ = self._issue_command(drone_id, CMD_TAKEOFF, float(req.altitude))
            resp.success = ok
            resp.result = 0 if ok else 4
            return resp
        return handler

    def _make_land_srv(self, drone_id: int):
        def handler(req: CommandTOL.Request, resp: CommandTOL.Response):
            ok, _ = self._issue_command(drone_id, CMD_LAND, 0.0)
            resp.success = ok
            resp.result = 0 if ok else 4
            return resp
        return handler

    def _on_drone_state_leader(self, ds: DroneState) -> None:
        pubs = self._remote_state_pubs.get(ds.drone_id)
        if pubs is None:
            return
        stamp = self.get_clock().now().to_msg()

        state = State()
        state.header.stamp = stamp
        state.connected = True
        state.armed = ds.armed
        state.guided = ds.mode == "GUIDED"
        state.mode = ds.mode
        pubs["state"].publish(state)

        pose = PoseStamped()
        pose.header.stamp = stamp
        pose.header.frame_id = "map"
        pose.pose.position.x = ds.x
        pose.pose.position.y = ds.y
        pose.pose.position.z = ds.z
        # Yaw -> quaternion (ENU, z-up).
        half = ds.yaw_rad * 0.5
        pose.pose.orientation.z = math.sin(half)
        pose.pose.orientation.w = math.cos(half)
        pubs["pose"].publish(pose)

        # We don't ship full GPS over the radio (no lat/lon in DroneState).
        # Publish a placeholder fix with altitude only so MavrosAdapter's
        # offset calibration knows the drone is "online"; offsets in the
        # field frame are configured statically in compose.demo.yaml
        # (FIELD_OFFSETS) for hardware.
        fix = NavSatFix()
        fix.header.stamp = stamp
        fix.altitude = ds.z
        fix.status.status = 0  # STATUS_FIX
        pubs["fix"].publish(fix)

    # ──────────────────────────────────────────────────────────────────────
    # Follower role: republish MAVROS over radio, replay radio commands
    # ──────────────────────────────────────────────────────────────────────
    def _init_follower(self) -> None:
        ns = f"/drone_{self._local_id}/mavros"

        self._state: State | None = None
        self._pose: PoseStamped | None = None
        self._fix: NavSatFix | None = None
        self._battery_pct: int = 0

        self.create_subscription(
            State, f"{ns}/state", self._on_local_state, _sensor_qos(),
            callback_group=self._cbg,
        )
        self.create_subscription(
            PoseStamped, f"{ns}/local_position/pose", self._on_local_pose,
            _sensor_qos(), callback_group=self._cbg,
        )
        self.create_subscription(
            NavSatFix, f"{ns}/global_position/global", self._on_local_fix,
            _sensor_qos(), callback_group=self._cbg,
        )

        self._setpoint_pub = self.create_publisher(
            PositionTarget, f"{ns}/setpoint_raw/local", 10,
        )
        self._arm_client = self.create_client(
            CommandBool, f"{ns}/cmd/arming", callback_group=self._cbg
        )
        self._mode_client = self.create_client(
            SetMode, f"{ns}/set_mode", callback_group=self._cbg
        )
        self._takeoff_client = self.create_client(
            CommandTOL, f"{ns}/cmd/takeoff", callback_group=self._cbg
        )
        self._land_client = self.create_client(
            CommandTOL, f"{ns}/cmd/land", callback_group=self._cbg
        )

    def _on_local_state(self, msg: State) -> None:
        self._state = msg

    def _on_local_pose(self, msg: PoseStamped) -> None:
        self._pose = msg

    def _on_local_fix(self, msg: NavSatFix) -> None:
        self._fix = msg

    def _publish_drone_state(self) -> None:
        if self._role != "follower":
            return
        pose = self._pose
        state = self._state
        if pose is None or state is None:
            return
        q = pose.pose.orientation
        # Yaw from quaternion (assume roll/pitch ~0 for ENU drone).
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny, cosy)
        self._link.send_drone_state(
            DroneState(
                time_boot_ms=self._link.boot_ms(),
                drone_id=self._local_id,
                x=pose.pose.position.x,
                y=pose.pose.position.y,
                z=pose.pose.position.z,
                yaw_rad=yaw,
                armed=bool(state.armed),
                ekf_ok=True,
                battery_pct=self._battery_pct,
                mode=state.mode or "",
            )
        )

    def _on_setpoint_follower(self, sp: Setpoint) -> None:
        if sp.drone_id != self._local_id and sp.drone_id != BROADCAST_DRONE_ID:
            return
        msg = PositionTarget()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.coordinate_frame = PositionTarget.FRAME_LOCAL_NED
        msg.type_mask = (
            PositionTarget.IGNORE_VX
            | PositionTarget.IGNORE_VY
            | PositionTarget.IGNORE_VZ
            | PositionTarget.IGNORE_AFX
            | PositionTarget.IGNORE_AFY
            | PositionTarget.IGNORE_AFZ
            | PositionTarget.IGNORE_YAW
            | PositionTarget.IGNORE_YAW_RATE
        )
        msg.position.x = sp.x
        msg.position.y = sp.y
        msg.position.z = sp.z
        self._setpoint_pub.publish(msg)

    def _on_command_follower(self, cmd: Command) -> None:
        if cmd.drone_id != self._local_id and cmd.drone_id != BROADCAST_DRONE_ID:
            return
        ok, message = self._execute_local_command(cmd.cmd, cmd.param_f)
        self._link.send_ack(
            Ack(
                time_boot_ms=self._link.boot_ms(),
                drone_id=self._local_id,
                seq=cmd.seq,
                success=ok,
                message=message[:39],
            )
        )

    def _execute_local_command(self, cmd: int, param_f: float) -> tuple[bool, str]:
        if cmd == CMD_ARM:
            return self._call_arming(True)
        if cmd == CMD_DISARM:
            return self._call_arming(False)
        if cmd == CMD_TAKEOFF:
            return self._call_takeoff(param_f)
        if cmd == CMD_LAND:
            return self._call_land()
        if cmd == CMD_SET_MODE_GUIDED:
            return self._call_set_mode("GUIDED")
        if cmd == CMD_SET_MODE_BRAKE:
            return self._call_set_mode("BRAKE")
        if cmd == CMD_ABORT:
            ok_b, _ = self._call_set_mode("BRAKE")
            ok_l, _ = self._call_land()
            return ok_b and ok_l, "abort: brake+land"
        return False, f"unknown cmd {cmd}"

    def _call_arming(self, value: bool) -> tuple[bool, str]:
        if not self._arm_client.wait_for_service(timeout_sec=2.0):
            return False, "arming service unavailable"
        req = CommandBool.Request()
        req.value = value
        fut = self._arm_client.call_async(req)
        return self._await_future(fut, "arming")

    def _call_set_mode(self, mode: str) -> tuple[bool, str]:
        if not self._mode_client.wait_for_service(timeout_sec=2.0):
            return False, "set_mode service unavailable"
        req = SetMode.Request()
        req.custom_mode = mode
        fut = self._mode_client.call_async(req)
        return self._await_future(fut, f"set_mode {mode}")

    def _call_takeoff(self, altitude: float) -> tuple[bool, str]:
        if not self._takeoff_client.wait_for_service(timeout_sec=2.0):
            return False, "takeoff service unavailable"
        req = CommandTOL.Request()
        req.altitude = altitude
        fut = self._takeoff_client.call_async(req)
        return self._await_future(fut, "takeoff")

    def _call_land(self) -> tuple[bool, str]:
        if not self._land_client.wait_for_service(timeout_sec=2.0):
            return False, "land service unavailable"
        req = CommandTOL.Request()
        fut = self._land_client.call_async(req)
        return self._await_future(fut, "land")

    @staticmethod
    def _await_future(future, label: str) -> tuple[bool, str]:
        deadline = time.monotonic() + 5.0
        while not future.done():
            if time.monotonic() > deadline:
                return False, f"{label}: timeout"
            time.sleep(0.02)
        res = future.result()
        if res is None:
            return False, f"{label}: no response"
        success = bool(getattr(res, "success", getattr(res, "mode_sent", False)))
        return success, label

    # ──────────────────────────────────────────────────────────────────────
    # Command issuing (leader → follower, with ACK matching)
    # ──────────────────────────────────────────────────────────────────────
    def _issue_command(self, drone_id: int, cmd: int, param_f: float) -> tuple[bool, str]:
        seq = self._tx_cmd_seq & 0xFFFF
        self._tx_cmd_seq = (self._tx_cmd_seq + 1) & 0xFFFF
        pending = _PendingAck(seq=seq, drone_id=drone_id)
        with self._pending_lock:
            self._pending_acks[seq] = pending
        try:
            self._link.send_command(
                Command(
                    time_boot_ms=self._link.boot_ms(),
                    drone_id=drone_id,
                    seq=seq,
                    cmd=cmd,
                    param_f=param_f,
                )
            )
            deadline = time.monotonic() + self._ack_timeout
            while time.monotonic() < deadline:
                if pending.event.wait(timeout=0.05):
                    return pending.success, pending.message
            return False, f"no ack from drone_{drone_id} within {self._ack_timeout}s"
        finally:
            with self._pending_lock:
                self._pending_acks.pop(seq, None)

    def _on_ack(self, ack: Ack) -> None:
        with self._pending_lock:
            pending = self._pending_acks.get(ack.seq)
        if pending is None:
            return
        pending.success = ack.success
        pending.message = ack.message
        pending.event.set()

    # ──────────────────────────────────────────────────────────────────────
    # Periodic
    # ──────────────────────────────────────────────────────────────────────
    def _poll_radio(self) -> None:
        for msg in self._link.poll():
            self._dispatch(msg)

    def _dispatch(self, msg: object) -> None:
        if isinstance(msg, DroneState):
            if self._role == "leader":
                self._on_drone_state_leader(msg)
        elif isinstance(msg, Setpoint):
            if self._role == "follower":
                self._on_setpoint_follower(msg)
        elif isinstance(msg, Command):
            if self._role == "follower":
                self._on_command_follower(msg)
        elif isinstance(msg, Ack):
            if self._role == "leader":
                self._on_ack(msg)
        elif isinstance(msg, Heartbeat):
            # Heartbeat presence already tracked via peer_age_s; nothing else.
            pass

    def _send_heartbeat(self) -> None:
        self._link.send_heartbeat(
            Heartbeat(
                time_boot_ms=self._link.boot_ms(),
                drone_id=self._local_id,
                role=ROLE_LEADER if self._role == "leader" else ROLE_FOLLOWER,
                uptime_s=int(time.monotonic() - self._t0),
            )
        )

    def _publish_link_age(self) -> None:
        ages = [self._link.peer_age_s(i) for i in range(self._drone_count)
                if i != self._local_id]
        finite = [a for a in ages if math.isfinite(a)]
        age = min(finite) if finite else float("inf")
        msg = Float32()
        msg.data = float(age) if math.isfinite(age) else -1.0
        self._link_age_pub.publish(msg)

    def _watchdog_tick(self) -> None:
        if self._role != "follower":
            return
        # Treat the leader (drone_id 0 by convention) as the peer-of-interest.
        leader_age = self._link.peer_age_s(0)
        if not math.isfinite(leader_age):
            return  # never heard from leader; do nothing until first frame.
        now = time.monotonic()
        if leader_age > self._disarm_after_s:
            if now - self._last_brake_action > 5.0:
                self.get_logger().error(
                    f"radio dead {leader_age:.1f}s — disarming"
                )
                self._call_arming(False)
                self._last_brake_action = now
        elif leader_age > self._brake_after_s:
            if now - self._last_brake_action > 5.0:
                self.get_logger().warning(
                    f"radio stale {leader_age:.1f}s — BRAKE"
                )
                self._call_set_mode("BRAKE")
                self._last_brake_action = now


class _PendingAck:
    __slots__ = ("seq", "drone_id", "success", "message", "event")

    def __init__(self, seq: int, drone_id: int) -> None:
        self.seq = seq
        self.drone_id = drone_id
        self.success = False
        self.message = ""
        self.event = threading.Event()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = RadioBridgeNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node._link.close()
        node.destroy_node()
        rclpy.shutdown()


__all__ = [
    "RadioBridgeNode",
    "LoopbackTransport",  # re-exported for tests
    "main",
]
