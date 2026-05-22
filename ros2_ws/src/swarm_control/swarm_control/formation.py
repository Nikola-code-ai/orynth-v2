"""Formation geometry for the swarm — Phase 2 (PLAN section D).

Ported from the v1 ``formation.py`` and extended with the line / V / column
layouts PLAN section F calls for. The module is **reference-agnostic**: a
formation is a set of *leader-relative* offsets, and :func:`place_formation`
projects them onto whatever reference pose it is handed — a static centroid for
the Phase 2 diamond hold, or the leader's live pose for the Phase 2.5 demo
(ADR 0008). It carries no ROS dependency, so the geometry stays unit-testable
without a running graph.

Frames
------
* **Formation-local** — ``(forward, left, up)`` in metres. Slot 0 is always the
  leader at the origin; every other slot is an offset *from the leader*.
* **Field ENU** — ``(east, north, up)`` in metres, the frame MAVROS publishes
  local position in. :func:`place_formation` rotates the formation-local
  offsets by ``heading`` (ENU yaw, radians CCW from East) and adds the
  reference point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Offset:
    """A leader-relative formation offset, ``(forward, left, up)`` in metres."""

    forward_m: float
    left_m: float
    up_m: float = 0.0


@dataclass(frozen=True)
class Formation:
    """A named set of leader-relative slot offsets, slot 0 = leader at origin."""

    name: str
    spacing_m: float
    offsets: tuple[Offset, ...]

    def __len__(self) -> int:
        return len(self.offsets)


# ── Layout generators — each returns leader-relative (forward, left) offsets ──
# Every generator places slot 0 at the origin (the leader) and the remaining
# slots behind / around it, so the whole formation is positioned by the
# leader's pose.


def _diamond(n: int, s: float) -> list[tuple[float, float]]:
    """5-ship diamond: leader at the front point, wings mid, slot at the tail.

    Slots: 0 leader (front) · 1 left wing · 2 right wing · 3 tail · 4 centre.
    Defined for 1-5 vehicles (it is a five-ship shape); truncated for fewer.
    """
    template = [
        (0.0, 0.0),  # 0 leader — front point
        (-s, +s),  # 1 left wing — back-left
        (-s, -s),  # 2 right wing — back-right
        (-2.0 * s, 0.0),  # 3 tail — directly behind
        (-s, 0.0),  # 4 centre — between the wings
    ]
    if not 1 <= n <= len(template):
        raise ValueError(f"diamond supports 1-{len(template)} vehicles, got {n}")
    return template[:n]


def _vee(n: int, s: float) -> list[tuple[float, float]]:
    """V / wedge: leader at the apex, followers trailing on alternating arms."""
    out = [(0.0, 0.0)]
    for i in range(1, n):
        arm = 1.0 if i % 2 == 1 else -1.0  # odd -> left, even -> right
        rank = (i + 1) // 2
        out.append((-rank * s, arm * rank * s))
    return out


def _column(n: int, s: float) -> list[tuple[float, float]]:
    """Single file: leader leads, each follower one spacing further back."""
    return [(-i * s, 0.0) for i in range(n)]


def _line(n: int, s: float) -> list[tuple[float, float]]:
    """Line abreast: leader at one end, followers extending to its left."""
    return [(0.0, i * s) for i in range(n)]


_GENERATORS = {
    "diamond": _diamond,
    "vee": _vee,
    "column": _column,
    "line": _line,
}

#: Formation names accepted by :func:`build_formation`.
FORMATION_NAMES = tuple(sorted(_GENERATORS))


def build_formation(name: str, vehicle_count: int, spacing_m: float) -> Formation:
    """Build a :class:`Formation` of ``vehicle_count`` leader-relative slots.

    Raises ``ValueError`` for an unknown name, a non-positive vehicle count, or
    a non-positive spacing — the swarm server surfaces these to the caller.
    """
    key = name.strip().lower()
    if key not in _GENERATORS:
        raise ValueError(
            f"unknown formation '{name}'; known: {', '.join(FORMATION_NAMES)}"
        )
    if vehicle_count < 1:
        raise ValueError(f"vehicle_count must be >= 1, got {vehicle_count}")
    if spacing_m <= 0.0:
        raise ValueError(f"spacing_m must be > 0, got {spacing_m}")

    pairs = _GENERATORS[key](vehicle_count, float(spacing_m))
    offsets = tuple(Offset(forward_m=f, left_m=l) for f, l in pairs)
    return Formation(name=key, spacing_m=float(spacing_m), offsets=offsets)


def place_formation(
    formation: Formation,
    reference: tuple[float, float, float],
    heading_rad: float = 0.0,
) -> list[tuple[float, float, float]]:
    """Project leader-relative offsets onto a field-ENU reference pose.

    ``reference`` is the leader / centroid position ``(east, north, up)``;
    ``heading_rad`` is the formation's forward direction as an ENU yaw (radians,
    CCW from East). Returns one absolute ``(east, north, up)`` target per slot,
    in slot order — slot 0 maps back onto ``reference`` exactly.
    """
    ref_e, ref_n, ref_u = reference
    cos_h, sin_h = math.cos(heading_rad), math.sin(heading_rad)
    targets: list[tuple[float, float, float]] = []
    for off in formation.offsets:
        # forward axis -> (cos, sin); left axis -> (-sin, cos).
        east = off.forward_m * cos_h - off.left_m * sin_h
        north = off.forward_m * sin_h + off.left_m * cos_h
        targets.append((ref_e + east, ref_n + north, ref_u + off.up_m))
    return targets


def horizontal_error(
    actual: tuple[float, float, float],
    target: tuple[float, float, float],
) -> float:
    """Horizontal (east-north) distance between two ENU points, in metres.

    This is the quantity the Phase 2 acceptance gate bounds at < 0.5 m mean
    drift per follower (PLAN section D).
    """
    return math.hypot(actual[0] - target[0], actual[1] - target[1])
