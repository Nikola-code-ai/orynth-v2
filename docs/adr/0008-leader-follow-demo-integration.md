# ADR 0008: Leader-follow integration for the hardware demo

**Status**: accepted · **Date**: 2026-05-21

## Context

After Phase 2 (5-drone SITL swarm + diamond formation) the project runs a
deliberately minimal **leader-follow demo** — Phase 2.5 in `PLAN.md` § D. An
operator manipulates the leader (`drone_0`) and the follower drones hold a
formation relative to it. The milestone runs in two stages: **2.5a** rehearses
leader-follow in the Gazebo SITL swarm; **2.5b** flies the same on real
airframes. The demo proves the swarm works before the heavier perception and
mapping phases; mapping and computer vision stay post-demo.

It needs a leader-follow mechanism. ArduPilot offers two viable paths:

1. **Native FOLLOW flight mode.** Each follower flies in `FOLLOW` mode with
   `FOLL_SYSID` set to the leader and a per-drone `FOLL_OFS_X/Y/Z` offset
   (`FOLL_OFS_TYPE` selects North-East-Down or leader-heading-relative). The
   leader broadcasts `GLOBAL_POSITION_INT` and the follower's autopilot closes
   the tracking loop in firmware; `FOLL_DIST_MAX` bounds it.
2. **GUIDED-mode companion-computer formation.** Followers fly `GUIDED`; each
   follower's companion computer computes a target from the leader's live pose
   and streams position setpoints. ArduPilot's own swarming guidance names
   "ROS + MAVROS" as the path for custom formation algorithms.

## Decision

Use **option 2** for the demo: a **ROS-side dynamic leader-relative formation**.
`swarm_server_node` subscribes to the leader's MAVROS pose and streams follower
position setpoints through `MavrosAdapter` (followers in GUIDED). This is
Phase 2's `formation.py` with its reference changed from a static centroid to
the leader's live pose. Native FOLLOW mode is kept as a documented fallback.

## Rationale

- **Reuses Phase 2 wholesale.** `formation.py`, `swarm_server_node`,
  `MavrosAdapter`, and the Cyclone DDS LAN already exist; the demo only
  generalizes the formation reference (static centroid → moving leader pose).
  FOLLOW mode would be a parallel, firmware-side path with its own bring-up.
- **No inter-FCU MAVLink mesh.** FOLLOW mode requires every follower's autopilot
  to receive the leader's `GLOBAL_POSITION_INT`. The plan (§ C) routes
  drone-to-drone over Cyclone DDS and drone-to-GCS over Zenoh — there is no
  MAVLink mesh, and building one solely for the demo is off-plan. The ROS-side
  controller carries the leader pose as an ordinary ROS topic on the LAN that
  already exists.
- **Holds the ADR 0002 invariant.** Followers are commanded via GUIDED setpoints
  through the `VehicleAdapter` — no MAVLink concepts leak above the adapter.
  FOLLOW mode would push formation logic into firmware `FOLL_*` parameters,
  outside the adapter contract.
- **Custom formation is the destination.** Phases 3-5 layer search patterns and
  detection-driven regrouping onto the formation controller; that logic must
  live in ROS, not in autopilot parameters.

## Consequences

- **Data path (Phase 2.5b, post-ADR 0009)**: the formation loop runs on the
  leader Jetson and sees a uniform `/drone_K/mavros/*` topic surface for every
  drone. For drone_0 (the leader) those topics come from a real MAVROS; for
  followers, they are *synthesised* locally by `radio_bridge` (role=leader)
  from inbound `ORYNTH_DRONE_STATE` frames over the SiK/RFD900 radio. The
  ROS-side controller is unchanged — the transport swap is hidden below it.
- **Watchdogs (two layers, post-ADR 0009)**:
  1. The original `leader_pose_timeout_s` watchdog in `swarm_server` (Phase
     2.5a) is unchanged — it still freezes followers on the last good
     reference if the leader pose ages past threshold.
  2. New `radio_bridge` follower-side watchdog: BRAKE after
     `radio_loss_brake_s` (default 2 s), DISARM after
     `radio_loss_disarm_s` (default 10 s) of radio silence. The follower
     does not wait for the leader to notice — it brings the airframe to
     safety on its own.
- `formation.py` is implemented reference-agnostic from Phase 2, so the demo
  feeds it a live leader pose with no rewrite.
- **Fallback**: if ROS-side tracking is too jittery on hardware, switch
  followers to native FOLLOW mode — set `FOLL_ENABLE`, `FOLL_SYSID`,
  `FOLL_OFS_TYPE`, per-drone `FOLL_OFS_*`, `FOLL_DIST_MAX`, and bridge the
  leader's `GLOBAL_POSITION_INT` to each follower via the SiK/RFD900 link
  (it's the same radio either way). The `MavrosAdapter` mode and parameter
  API already covers the set-up; only the inter-vehicle position bridge is
  new.
- Revisit if the demo scope grows toward the Phase 7 field mission, or if
  AP_DDS parity (ADR 0002) changes the bridge options.

## References

- ArduPilot Copter — Follow Mode: <https://ardupilot.org/copter/docs/follow-mode.html>
- ArduPilot — Swarming (Mission Planner): <https://ardupilot.org/planner/docs/swarming.html>
