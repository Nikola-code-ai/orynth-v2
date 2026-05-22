"""Phase 1 unit tests for the ROS-free control-layer types in ``swarm_api``.

These mirror the v1 ``test_swarm_components`` suite (PLAN section F): pure
types and geometry, no ROS runtime required.
"""

import dataclasses

import pytest

from swarm_control.swarm_api import (
    AutonomyMode,
    FollowReferenceRequest,
    MotionTarget,
    PlatformProfile,
    SwarmStatusSnapshot,
    TakeoffRequest,
    VehicleHealth,
)


def test_platform_profile_is_mavros_only():
    # v2 dropped the v1 AEROSTACK2_SIM profile (ADR 0002).
    assert {p.value for p in PlatformProfile} == {
        "ardupilot_sitl",
        "ardupilot_hardware",
    }


def test_platform_profile_is_str_enum():
    assert PlatformProfile.ARDUPILOT_SITL == "ardupilot_sitl"


def test_autonomy_mode_members():
    assert AutonomyMode.SAFETY_ABORT.value == "safety_abort"
    assert len(AutonomyMode) == 4


def test_motion_target_defaults_to_map_frame():
    target = MotionTarget(point=(10.0, 0.0, 5.0), speed_mps=2.0)
    assert target.frame_id == "map"
    assert target.point == (10.0, 0.0, 5.0)


def test_requests_are_frozen():
    takeoff = TakeoffRequest(height_m=5.0, speed_mps=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        takeoff.height_m = 9.0  # type: ignore[misc]


def test_follow_reference_request_fields():
    req = FollowReferenceRequest(
        x=1.0,
        y=2.0,
        z=3.0,
        frame_id="map",
        speed_x_mps=0.5,
        speed_y_mps=0.5,
        speed_z_mps=0.5,
    )
    assert (req.x, req.y, req.z) == (1.0, 2.0, 3.0)


def test_swarm_status_snapshot_construction():
    snap = SwarmStatusSnapshot(
        platform_profile=PlatformProfile.ARDUPILOT_SITL,
        autonomy_mode=AutonomyMode.MANUAL_LEADER,
        leader_id="drone_0",
        formation_name="none",
        active_vehicles=("drone_0",),
    )
    assert snap.leader_id == "drone_0"
    assert snap.active_vehicles == ("drone_0",)


def test_vehicle_health_construction():
    health = VehicleHealth(
        vehicle_id="drone_0",
        connected=True,
        armed=False,
        external_control=True,
    )
    assert health.connected and health.external_control
    assert not health.armed
