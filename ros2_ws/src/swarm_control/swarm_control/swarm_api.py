"""Shared control-layer types for swarm orchestration.

Ported from the v1 ``aerolab_simulation.swarm_api`` module (PLAN section F:
"port verbatim"). Two v2 adaptations:

* the v1 ``AEROSTACK2_SIM`` platform profile is dropped — v2 is MAVROS /
  ArduPilot-only (ADR 0002);
* v1's ``ARDUPILOT_REAL`` becomes ``ARDUPILOT_HARDWARE`` (PLAN section F).

These types are deliberately ROS-free: the control logic that consumes them
stays unit-testable without a running ROS graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlatformProfile(str, Enum):
    """Underlying flight-platform implementation behind a ``VehicleAdapter``."""

    ARDUPILOT_SITL = "ardupilot_sitl"
    ARDUPILOT_HARDWARE = "ardupilot_hardware"


class AutonomyMode(str, Enum):
    """High-level swarm autonomy state owned by the controller (Phase 2+)."""

    MANUAL_LEADER = "manual_leader"
    FORMATION_HOLD = "formation_hold"
    FORMATION_MISSION = "formation_mission"
    SAFETY_ABORT = "safety_abort"


@dataclass(frozen=True)
class TakeoffRequest:
    """Vertical takeoff to ``height_m`` above the arming altitude."""

    height_m: float
    speed_mps: float


@dataclass(frozen=True)
class LandRequest:
    """Descent to ground at ``speed_mps``."""

    speed_mps: float


@dataclass(frozen=True)
class MotionTarget:
    """A point-to-point motion goal expressed in ``frame_id``.

    ``point`` is ``(x, y, z)``. For the MAVROS backend the default frame is the
    ENU local frame MAVROS publishes pose in (REP-105 ``map``).
    """

    point: tuple[float, float, float]
    speed_mps: float
    frame_id: str = "map"


@dataclass(frozen=True)
class FollowReferenceRequest:
    """Track a moving reference frame — used by formation hold (Phase 2)."""

    x: float
    y: float
    z: float
    frame_id: str
    speed_x_mps: float
    speed_y_mps: float
    speed_z_mps: float


@dataclass(frozen=True)
class VehicleHealth:
    """Snapshot of a single vehicle's connection / arming state."""

    vehicle_id: str
    connected: bool
    armed: bool
    external_control: bool


@dataclass(frozen=True)
class SwarmStatusSnapshot:
    """Immutable swarm-wide status — consumed by the GCS (Phase 2)."""

    platform_profile: PlatformProfile
    autonomy_mode: AutonomyMode
    leader_id: str
    formation_name: str
    active_vehicles: tuple[str, ...]
