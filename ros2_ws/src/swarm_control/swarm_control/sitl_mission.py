"""Phase 1 SITL acceptance mission.

Drives a single ArduPilot SITL drone through the Phase 1 acceptance sequence
(PLAN section D): connect -> GUIDED -> arm -> takeoff 5 m -> waypoint
(10, 0, 5) -> land. Invoked headless by ``scripts/ci/run_sitl_smoke.sh``.

Exit code 0 = mission complete; non-zero = a step failed or timed out. The
mission talks only to ``MavrosAdapter`` — it has no MAVLink/MAVROS knowledge of
its own, which keeps it reusable against a future AP_DDS backend (ADR 0002).
"""

from __future__ import annotations

import threading

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from .mavros_adapter import MavrosAdapter
from .swarm_api import LandRequest, MotionTarget, TakeoffRequest
from .vehicle_adapter import VehicleAdapter

#: Phase 1 acceptance parameters (PLAN section D).
TAKEOFF_HEIGHT_M = 5.0
TAKEOFF_SPEED_MPS = 1.0
WAYPOINT_XYZ = (10.0, 0.0, 5.0)
CRUISE_SPEED_MPS = 2.0
LAND_SPEED_MPS = 0.5


def run_mission(adapter: VehicleAdapter, logger) -> bool:
    """Execute the Phase 1 mission; return True iff every step succeeds."""
    logger.info("step 1/5 — waiting for FCU connection")
    if not adapter.wait_for_connection(timeout_s=60.0):
        return False

    logger.info("step 2/5 — switching to GUIDED")
    if not adapter.enable_external_control():
        return False

    logger.info("step 3/5 — arming")
    if not adapter.arm():
        return False

    logger.info(f"step 4/5 — takeoff to {TAKEOFF_HEIGHT_M:.0f} m")
    takeoff = TakeoffRequest(height_m=TAKEOFF_HEIGHT_M, speed_mps=TAKEOFF_SPEED_MPS)
    if not adapter.takeoff(takeoff):
        return False

    logger.info(f"step 4/5 — waypoint to {WAYPOINT_XYZ}")
    waypoint = MotionTarget(point=WAYPOINT_XYZ, speed_mps=CRUISE_SPEED_MPS)
    if not adapter.go_to(waypoint):
        return False

    logger.info("step 5/5 — landing")
    if not adapter.land(LandRequest(speed_mps=LAND_SPEED_MPS)):
        return False

    logger.info("mission complete — arm, takeoff, waypoint, land all OK")
    return True


def main(args: list[str] | None = None) -> int:
    """Entry point for ``ros2 run swarm_control sitl_mission``."""
    rclpy.init(args=args)
    node = Node("sitl_mission")
    logger = node.get_logger()
    adapter = MavrosAdapter(node, vehicle_id="drone_0")

    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    ok = False
    try:
        ok = run_mission(adapter, logger)
    except Exception as exc:  # surface any unexpected failure as exit != 0
        logger.error(f"mission aborted: {exc!r}")
    finally:
        if not ok:
            logger.error("mission FAILED")
        # Stop the executor and join its thread before destroying entities,
        # so nothing is torn down while a callback may still touch it.
        executor.shutdown()
        spin_thread.join(timeout=5.0)
        adapter.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
