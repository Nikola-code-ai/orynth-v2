"""Phase 2 unit tests for the ROS-free formation geometry in ``formation``.

Pure types and geometry, no ROS runtime required (PLAN section E — formation
math, ported + extended).
"""

import math

import pytest

from swarm_control.formation import (
    FORMATION_NAMES,
    build_formation,
    horizontal_error,
    place_formation,
)


def test_known_formation_names():
    assert FORMATION_NAMES == ("column", "diamond", "line", "vee")


def test_diamond_has_five_leader_relative_slots():
    f = build_formation("diamond", 5, spacing_m=3.0)
    assert len(f) == 5
    assert f.name == "diamond"
    # Slot 0 is always the leader, at the formation-local origin.
    assert (f.offsets[0].forward_m, f.offsets[0].left_m) == (0.0, 0.0)


def test_diamond_offsets():
    f = build_formation("diamond", 5, spacing_m=3.0)
    fwd_left = [(o.forward_m, o.left_m) for o in f.offsets]
    assert fwd_left == [
        (0.0, 0.0),  # leader — front point
        (-3.0, 3.0),  # left wing
        (-3.0, -3.0),  # right wing
        (-6.0, 0.0),  # tail
        (-3.0, 0.0),  # centre
    ]


def test_diamond_is_truncated_for_fewer_vehicles():
    assert len(build_formation("diamond", 3, spacing_m=2.0)) == 3


def test_diamond_rejects_more_than_five():
    with pytest.raises(ValueError):
        build_formation("diamond", 6, spacing_m=2.0)


def test_vee_alternates_arms_by_rank():
    f = build_formation("vee", 5, spacing_m=2.0)
    fwd_left = [(o.forward_m, o.left_m) for o in f.offsets]
    assert fwd_left == [
        (0.0, 0.0),
        (-2.0, 2.0),  # rank 1, left
        (-2.0, -2.0),  # rank 1, right
        (-4.0, 4.0),  # rank 2, left
        (-4.0, -4.0),  # rank 2, right
    ]


def test_column_is_single_file():
    f = build_formation("column", 4, spacing_m=2.5)
    assert [o.forward_m for o in f.offsets] == [0.0, -2.5, -5.0, -7.5]
    assert all(o.left_m == 0.0 for o in f.offsets)


def test_line_is_abreast():
    f = build_formation("line", 3, spacing_m=4.0)
    assert [o.left_m for o in f.offsets] == [0.0, 4.0, 8.0]
    assert all(o.forward_m == 0.0 for o in f.offsets)


def test_unknown_formation_raises():
    with pytest.raises(ValueError):
        build_formation("wedge", 5, spacing_m=3.0)


def test_non_positive_spacing_or_count_raises():
    with pytest.raises(ValueError):
        build_formation("diamond", 5, spacing_m=0.0)
    with pytest.raises(ValueError):
        build_formation("diamond", 0, spacing_m=3.0)


def test_place_formation_slot_zero_maps_onto_reference():
    f = build_formation("diamond", 5, spacing_m=3.0)
    ref = (10.0, 20.0, 5.0)
    targets = place_formation(f, ref, heading_rad=0.0)
    assert targets[0] == pytest.approx(ref)


def test_place_formation_heading_zero_is_forward_east():
    f = build_formation("diamond", 5, spacing_m=3.0)
    targets = place_formation(f, (10.0, 20.0, 5.0), heading_rad=0.0)
    # heading 0 -> forward axis is +East, left axis is +North.
    assert targets[1] == pytest.approx((7.0, 23.0, 5.0))  # (-3 fwd, +3 left)
    assert targets[3] == pytest.approx((4.0, 20.0, 5.0))  # (-6 fwd, 0 left)


def test_place_formation_rotates_by_heading():
    f = build_formation("diamond", 5, spacing_m=3.0)
    targets = place_formation(f, (10.0, 20.0, 5.0), heading_rad=math.pi / 2.0)
    # 90 deg CCW: left wing (-3 fwd, +3 left) -> (-3 East, -3 North).
    assert targets[1] == pytest.approx((7.0, 17.0, 5.0))


def test_place_formation_preserves_spacing_under_rotation():
    f = build_formation("diamond", 5, spacing_m=3.0)
    ref = (0.0, 0.0, 5.0)
    for heading in (0.0, 0.7, math.pi, 2.5):
        targets = place_formation(f, ref, heading_rad=heading)
        # tail slot is 2*spacing behind the leader, at any heading.
        assert horizontal_error(targets[3], targets[0]) == pytest.approx(6.0)


def test_horizontal_error_ignores_altitude():
    assert horizontal_error((0.0, 0.0, 0.0), (3.0, 4.0, 99.0)) == pytest.approx(5.0)
