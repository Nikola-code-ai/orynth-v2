"""swarm_server_node — Phase 2 five-drone orchestrator (PLAN section D / I, #5).

Owns one :class:`MavrosAdapter` per drone and exposes the swarm command
surface, all in the backend-neutral control layer (ADR 0002 — no MAVLink leaks
above the adapter):

* ``/swarm/takeoff``               (swarm_msgs/SwarmTakeoff) — coordinated takeoff
* ``/swarm/land``                  (std_srvs/Trigger)        — coordinated land
* ``/swarm/engage_formation``      (swarm_msgs/SetFormation) — hold a formation
* ``/swarm/drone_<N>/manual_goto`` (swarm_msgs/ManualGoto)   — detach + fly one

It streams formation-hold setpoints from a fixed timer and publishes
``swarm_msgs/SwarmStatus`` for the GCS / Foxglove ``operator.json`` layout.

Frames
------
Every drone's MAVROS ``local_position`` is relative to its own EKF origin. The
``field_offsets`` parameter gives each drone's spawn position in a shared
*field* ENU frame; the server adds it to read a drone's field position and
subtracts it to command one. For pure-SITL with a shared home the offsets are
all zero and field == local.

Concurrency
-----------
All adapter entities, the four services and both timers share one
:class:`ReentrantCallbackGroup` under a :class:`MultiThreadedExecutor`, so the
per-drone blocking calls (arm, takeoff, land) — fanned out across a thread pool
— run in parallel without starving telemetry.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from threading import RLock

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_srvs.srv import Trigger
from swarm_msgs.msg import DroneState, SwarmStatus
from swarm_msgs.srv import ManualGoto, SetFormation, SwarmTakeoff

from .formation import (
    FORMATION_NAMES,
    Formation,
    build_formation,
    horizontal_error,
    place_formation,
)
from .mavros_adapter import MavrosAdapter
from .swarm_api import FollowReferenceRequest, LandRequest, MotionTarget, TakeoffRequest


class SwarmServer(Node):
    """Orchestrates N ArduPilot drones through their MavrosAdapters."""

    def __init__(self) -> None:
        super().__init__("swarm_server")

        self.declare_parameter("drone_count", 5)
        self.declare_parameter("mavros_ns_prefix", "drone_")
        self.declare_parameter("takeoff_altitude_m", 5.0)
        self.declare_parameter("cruise_speed_mps", 2.0)
        self.declare_parameter("formation_rate_hz", 10.0)
        self.declare_parameter("status_rate_hz", 2.0)
        # Per-slot altitude separation. 0 = flat formation (pure-SITL, where
        # drones fly in independent worlds). A positive step deconflicts a
        # shared-world sim: slot i holds altitude + i*step so drones never
        # share a point in space while crossing into formation.
        self.declare_parameter("formation_alt_step_m", 0.0)

        self._n = int(self.get_parameter("drone_count").value)
        prefix = str(self.get_parameter("mavros_ns_prefix").value)
        self._takeoff_alt = float(self.get_parameter("takeoff_altitude_m").value)
        self._cruise = float(self.get_parameter("cruise_speed_mps").value)
        self._formation_hz = float(self.get_parameter("formation_rate_hz").value)
        status_hz = float(self.get_parameter("status_rate_hz").value)
        self._alt_step = float(self.get_parameter("formation_alt_step_m").value)

        # Per-drone field-frame spawn offsets, flat [x0,y0,x1,y1,...].
        self.declare_parameter("field_offsets", [0.0] * (2 * self._n))
        flat = list(self.get_parameter("field_offsets").value)
        if len(flat) != 2 * self._n:
            self.get_logger().warn(
                f"field_offsets has {len(flat)} values, expected {2 * self._n} "
                "— defaulting all offsets to zero (shared-home SITL)"
            )
            flat = [0.0] * (2 * self._n)
        self._offsets = [(flat[2 * i], flat[2 * i + 1]) for i in range(self._n)]

        # One reentrant group: the MultiThreadedExecutor may run any callback
        # (or re-enter one) on any thread — required so blocking arm/takeoff
        # service handlers do not deadlock against adapter service clients.
        self._cbg = ReentrantCallbackGroup()
        self._adapters: list[MavrosAdapter] = [
            MavrosAdapter(
                self,
                vehicle_id=f"drone_{i}",
                mavros_ns=f"{prefix}{i}/mavros",
                callback_group=self._cbg,
            )
            for i in range(self._n)
        ]

        # Mission state, guarded by _lock.
        self._lock = RLock()
        self._phase = "idle"
        self._formation: Formation | None = None
        self._formation_ref: tuple[float, float, float] | None = None
        self._heading_rad = 0.0
        self._manual: set[int] = set()
        self._tick = 0

        self.create_service(
            SwarmTakeoff, "/swarm/takeoff", self._on_takeoff, callback_group=self._cbg
        )
        self.create_service(
            Trigger, "/swarm/land", self._on_land, callback_group=self._cbg
        )
        self.create_service(
            SetFormation,
            "/swarm/engage_formation",
            self._on_engage_formation,
            callback_group=self._cbg,
        )
        for i in range(self._n):
            self.create_service(
                ManualGoto,
                f"/swarm/drone_{i}/manual_goto",
                self._make_goto_cb(i),
                callback_group=self._cbg,
            )

        self._status_pub = self.create_publisher(SwarmStatus, "/swarm/status", 5)
        self.create_timer(
            1.0 / self._formation_hz, self._formation_tick, callback_group=self._cbg
        )
        self.create_timer(
            1.0 / status_hz, self._publish_status, callback_group=self._cbg
        )

        self.get_logger().info(
            f"swarm_server up — {self._n} drones, formations: "
            f"{', '.join(FORMATION_NAMES)}"
        )

    # ── Service handlers ────────────────────────────────────────────────────
    def _on_takeoff(self, request, response):
        """Coordinated connect -> GUIDED -> arm -> takeoff across all drones."""
        altitude = request.altitude_m if request.altitude_m > 0.0 else self._takeoff_alt
        self.get_logger().info(f"/swarm/takeoff — all drones to {altitude:.1f} m")
        self._set_phase("taking_off", clear_manual=True, clear_formation=True)

        results = self._parallel(
            lambda adapter: self._drone_takeoff(adapter, altitude), "takeoff"
        )
        ok = all(results.values())
        self._set_phase("airborne" if ok else "idle")
        response.success = ok
        response.message = self._summary("takeoff", results)
        self.get_logger().info(response.message)
        return response

    def _on_land(self, request, response):
        """Coordinated land + disarm across all drones."""
        self.get_logger().info("/swarm/land — all drones")
        self._set_phase("landing", clear_manual=True, clear_formation=True)
        results = self._parallel(
            lambda adapter: adapter.land(LandRequest(speed_mps=0.5)), "land"
        )
        ok = all(results.values())
        self._set_phase("landed" if ok else "airborne")
        response.success = ok
        response.message = self._summary("land", results)
        self.get_logger().info(response.message)
        return response

    def _on_engage_formation(self, request, response):
        """Latch a formation; the formation timer streams the hold setpoints."""
        try:
            formation = build_formation(
                request.formation_name, self._n, request.spacing_m
            )
        except ValueError as exc:
            response.success = False
            response.message = str(exc)
            self.get_logger().error(f"engage_formation rejected: {exc}")
            return response

        if not self._calibrate_offsets():
            self.get_logger().warn(
                "GPS unavailable on some drones — keeping configured field_offsets"
            )
        ref = self._field_position(0)
        if ref is None:
            response.success = False
            response.message = "leader (drone_0) has no pose yet — takeoff first"
            self.get_logger().error(response.message)
            return response

        with self._lock:
            self._formation = formation
            self._formation_ref = ref
            self._heading_rad = math.radians(request.heading_deg)
            self._manual.clear()
            self._phase = "formation_hold"
        response.success = True
        response.message = (
            f"holding '{formation.name}' spacing={formation.spacing_m:.1f} m "
            f"heading={request.heading_deg:.0f} deg around "
            f"({ref[0]:.1f}, {ref[1]:.1f}, {ref[2]:.1f})"
        )
        self.get_logger().info(response.message)
        return response

    def _make_goto_cb(self, index: int):
        """Build the /swarm/drone_<index>/manual_goto handler."""

        def _on_manual_goto(request, response):
            adapter = self._adapters[index]
            ox, oy = self._offsets[index]
            field = (request.target.x, request.target.y, request.target.z)
            local = (field[0] - ox, field[1] - oy, field[2])
            self.get_logger().info(
                f"/swarm/drone_{index}/manual_goto -> field "
                f"({field[0]:.1f}, {field[1]:.1f}, {field[2]:.1f})"
            )
            with self._lock:
                self._manual.add(index)  # detach from formation hold
            adapter.cancel_motion()
            ok = adapter.go_to(MotionTarget(point=local, speed_mps=self._cruise))
            response.success = ok
            response.message = (
                f"drone_{index} reached target"
                if ok
                else f"drone_{index} did not reach target"
            )
            return response

        return _on_manual_goto

    # ── Formation control loop ──────────────────────────────────────────────
    def _formation_tick(self) -> None:
        """Stream one hold setpoint per drone while a formation is engaged."""
        with self._lock:
            if self._phase != "formation_hold" or self._formation is None:
                return
            formation = self._formation
            ref = self._formation_ref
            heading = self._heading_rad
            manual = set(self._manual)
            self._tick += 1
            tick = self._tick

        if ref is None:
            return
        targets = place_formation(formation, ref, heading)
        for i, adapter in enumerate(self._adapters):
            if i in manual or i >= len(targets):
                continue
            tx, ty, tz = targets[i]
            ox, oy = self._offsets[i]
            adapter.hold_reference(
                FollowReferenceRequest(
                    x=tx - ox,
                    y=ty - oy,
                    z=tz + i * self._alt_step,
                    frame_id="map",
                    speed_x_mps=0.0,
                    speed_y_mps=0.0,
                    speed_z_mps=0.0,
                )
            )

        # ~1 Hz drift report — the Phase 2 acceptance gate (<0.5 m mean).
        rate_ticks = max(1, int(round(self._formation_hz)))
        if tick % rate_ticks == 0:
            self._log_drift(formation, targets, manual)

    def _log_drift(self, formation, targets, manual: set[int]) -> None:
        errors: dict[int, float] = {}
        for i in range(1, self._n):  # followers only (slot 0 is the leader)
            if i in manual:
                continue
            field = self._field_position(i)
            if field is None or i >= len(targets):
                continue
            errors[i] = horizontal_error(field, targets[i])
        if not errors:
            return
        mean = sum(errors.values()) / len(errors)
        worst = max(errors.values())
        detail = " ".join(f"drone_{i}={e:.2f}m" for i, e in sorted(errors.items()))
        self.get_logger().info(
            f"{formation.name} hold | drift mean={mean:.2f}m max={worst:.2f}m | {detail}"
        )

    # ── Status publishing ───────────────────────────────────────────────────
    def _publish_status(self) -> None:
        msg = SwarmStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "field"
        with self._lock:
            msg.formation = self._formation.name if self._formation else "none"
            msg.mission_phase = self._phase
        msg.leader_id = 0
        msg.mission_progress = 0.0
        msg.emergency = False
        msg.emergency_reason = ""
        for i, adapter in enumerate(self._adapters):
            ds = DroneState()
            ds.header = msg.header
            ds.drone_id = i
            ds.mode = adapter.mode
            ds.armed = adapter.armed
            field = self._field_position(i)
            pose = PoseStamped()
            pose.header = msg.header
            if field is not None:
                pose.pose.position.x = field[0]
                pose.pose.position.y = field[1]
                pose.pose.position.z = field[2]
            ds.pose = pose
            connected = adapter.connected
            ds.ekf_ok = connected
            ds.status = DroneState.STATUS_OK if connected else DroneState.STATUS_FAIL
            ds.status_message = "" if connected else "no FCU heartbeat"
            msg.drones.append(ds)
        self._status_pub.publish(msg)

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _drone_takeoff(self, adapter: MavrosAdapter, altitude: float) -> bool:
        """connect -> GUIDED -> arm -> takeoff for one drone (blocking)."""
        if not adapter.wait_for_connection(timeout_s=60.0):
            return False
        if not adapter.enable_external_control():
            return False
        if not adapter.arm():
            return False
        return adapter.takeoff(TakeoffRequest(height_m=altitude, speed_mps=1.0))

    def _parallel(self, fn, label: str) -> dict[int, bool]:
        """Run ``fn(adapter)`` for every drone in parallel; collect bool results."""
        results: dict[int, bool] = {}
        with ThreadPoolExecutor(max_workers=self._n) as pool:
            futures = {pool.submit(fn, a): i for i, a in enumerate(self._adapters)}
            for fut, i in futures.items():
                try:
                    results[i] = bool(fut.result())
                except Exception as exc:  # noqa: BLE001 — surface as a failure
                    self.get_logger().error(f"{label} drone_{i} raised: {exc!r}")
                    results[i] = False
        return results

    def _calibrate_offsets(self) -> bool:
        """Derive each drone's field-frame offset from its GPS fix.

        Drones in independent EKF frames are not directly comparable. This
        anchors them in one ENU frame with a flat-earth projection about the
        leader's fix: shared-home SITL yields ~zero offsets, a Gazebo world
        with spread spawns yields the real separations. Returns False — and
        leaves ``self._offsets`` untouched — if any drone has no fix yet.
        """
        earth_r = 6_378_137.0
        base = self._adapters[0].global_position
        if base is None:
            return False
        lat0, lon0 = base[0], base[1]
        cos_lat0 = math.cos(math.radians(lat0))
        offsets: list[tuple[float, float]] = []
        for adapter in self._adapters:
            fix = adapter.global_position
            if fix is None:
                return False
            d_east = math.radians(fix[1] - lon0) * earth_r * cos_lat0
            d_north = math.radians(fix[0] - lat0) * earth_r
            offsets.append((d_east, d_north))
        self._offsets = offsets
        self.get_logger().info(
            "field offsets calibrated from GPS: "
            + ", ".join(
                f"drone_{i}=({e:.1f},{n:.1f})" for i, (e, n) in enumerate(offsets)
            )
        )
        return True

    def _field_position(self, index: int) -> tuple[float, float, float] | None:
        """A drone's position in the shared field ENU frame, or None."""
        local = self._adapters[index].local_position
        if local is None:
            return None
        ox, oy = self._offsets[index]
        return (local[0] + ox, local[1] + oy, local[2])

    def _set_phase(
        self, phase: str, *, clear_manual: bool = False, clear_formation: bool = False
    ) -> None:
        with self._lock:
            self._phase = phase
            if clear_manual:
                self._manual.clear()
            if clear_formation:
                self._formation = None
                self._formation_ref = None

    @staticmethod
    def _summary(action: str, results: dict[int, bool]) -> str:
        ok = sorted(i for i, v in results.items() if v)
        bad = sorted(i for i, v in results.items() if not v)
        if not bad:
            return f"{action}: all {len(ok)} drones OK"
        return f"{action}: {len(ok)} OK, failed {bad}"

    def shutdown(self) -> None:
        for adapter in self._adapters:
            adapter.close()


def main(args: list[str] | None = None) -> int:
    """Entry point for ``ros2 run swarm_control swarm_server``."""
    rclpy.init(args=args)
    node = SwarmServer()
    executor = MultiThreadedExecutor(num_threads=16)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
