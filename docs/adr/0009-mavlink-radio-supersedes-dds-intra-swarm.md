# ADR 0009: SiK/RFD900 MAVLink radio for inter-drone comms; DDS becomes per-Jetson

**Status**: accepted · **Date**: 2026-05-23
**Supersedes (in part)**: ADR 0004 — the intra-swarm half. The Zenoh GCS-edge
half of ADR 0004 is retained.

## Context

Phase 2.5b is the first hardware flight. ADR 0004 assumed a shared WiFi LAN
carrying Cyclone DDS between every Jetson. Hardware experience says:

- WiFi range and reliability are inadequate for an outdoor leader-follow flight
  beyond ~50 m, especially with the antennas onboard small airframes.
- Multicast discovery is regularly dropped by available APs; the peer-list
  fallback (`cyclonedds_drone_<N>.xml`) is a config-maintenance burden that
  only papered over the deeper transport problem.
- The community-standard inter-drone link for ArduPilot-based swarms is
  serial MAVLink telemetry radios (SiK firmware on HM-TRP and RFD900x
  hardware), which are field-deployable, robust, and well-supported by the
  ecosystem.

Mesh-IP radios (Doodle Labs, Microhard) preserve DDS but cost >10× per node
and are out of budget for the 2-drone Phase 2.5b airframe set.

## Decision

- **Inter-drone link** is **SiK / RFD900x telemetry radio** carrying a custom
  MAVLink dialect (`orynth_swarm.xml`, messages 220–224). One radio per
  Jetson, wired to the Jetson's USB-UART; the FC is **not** on the radio link.
- **Cyclone DDS becomes Jetson-local**. Each Jetson uses
  - a unique `ROS_DOMAIN_ID = 100 + DRONE_ID`, and
  - `cyclonedds_local_only.xml` binding DDS to the `lo` interface.
- **`swarm_radio` package** provides a single `radio_bridge` ROS 2 node that
  runs on every Jetson in one of two roles:
  - **leader**: synthesizes a fake `/drone_K/mavros/*` topic/service surface
    for each follower drone K from incoming radio frames, and ships outbound
    setpoints over the radio. This trick keeps `swarm_server` and
    `MavrosAdapter` unchanged — they cannot tell the difference between a
    real MAVROS and a radio-backed synthetic one.
  - **follower**: republishes its own MAVROS state/pose over the radio at
    10 Hz, replays incoming setpoints onto its local MAVROS, executes
    incoming commands via local MAVROS service calls and ACKs them.

## Rationale

- **Field-deployable transport.** RFD900x is the de-facto MAVLink radio for
  ArduPilot beyond visual range, with order-of-magnitude better range than
  the on-airframe WiFi we were assuming.
- **Minimal blast radius on existing code.** `swarm_server`, `MavrosAdapter`,
  `formation.py`, and every service contract under `swarm_msgs/srv/*` stay
  byte-for-byte unchanged. The transport swap is hidden behind the same
  `/drone_K/mavros/*` topic surface they already consume.
- **Bandwidth headroom.** Phase 2.5b ships ~6.4 kbps over a radio that
  carries ~38 kbps usable at 64 kbps air rate. Room for command bursts and a
  third drone without re-architecting.
- **Hand-rolled framing, no codegen.** Five message types defined in
  `external/mavlink_dialects/orynth_swarm.xml`; encode/decode is ~200 lines of
  pure Python in `swarm_radio.radio_link`. No `mavgen` step at colcon-build
  time. The XML is still the authoritative spec.
- **Defence in depth against DDS bleed.** Both per-Jetson `ROS_DOMAIN_ID`
  *and* DDS-on-`lo` are configured; either alone is sufficient, both
  together protect against accidental WiFi-DDS revival during dev.
- **ADR 0002 invariant holds.** MAVLink concepts are still confined to the
  transport layer (`swarm_radio`). `MavrosAdapter` still sees only
  ROS messages. Followers still fly GUIDED via setpoints.

## Consequences

- **New failure mode**: radio loss. Mitigations:
  - Follower-side watchdog (in `radio_bridge`): if no leader frame for
    `radio_loss_brake_s` (default 2.0 s), command FC into `BRAKE`. If no
    frame for `radio_loss_disarm_s` (default 10 s), disarm.
  - Existing `leader_pose_timeout_s` watchdog in `swarm_server` continues to
    function — leader's view of follower poses ages out the same way.
- **No GPS lat/lon over the radio.** `ORYNTH_DRONE_STATE` carries only the
  ENU position in the field frame. `MavrosAdapter`'s GPS-offset calibration
  must be done via static `FIELD_OFFSETS` env (or a one-shot calibration
  pass before flight) rather than live GPS reads on followers. Acceptable
  trade-off for compact frames and Phase 2.5b's surveyed-takeoff workflow.
- **Jetson death = radio death.** If a Jetson reboots, its radio link drops.
  Mitigated by the FC retaining RC override and the follower watchdog
  bringing the airframe to BRAKE / DISARM autonomously.
- **SITL is unaffected.** The Gazebo 5-drone swarm keeps Cyclone DDS on
  `127.0.0.1` for now (`compose.swarm.yaml`). A simulated-radio mode is
  out-of-scope for Phase 2.5b; add it when we need to test radio failure
  modes in sim.
- **ADR 0004 is partially superseded.** The "intra-swarm Cyclone DDS"
  decision no longer applies above the Jetson boundary. The Zenoh
  GCS-edge half of ADR 0004 is independent and remains in force for the
  drone-to-GCS link.

## Implementation

- New package: `ros2_ws/src/swarm_radio/`
  - `swarm_radio/radio_link.py` — transport + framing (no ROS deps)
  - `swarm_radio/radio_bridge_node.py` — bidirectional bridge node
  - `swarm_radio/dialect.py` — runtime dialect loader
  - `test/test_radio_link.py` — encode/decode round-trip, watchdog, resync
- New dialect: `external/mavlink_dialects/orynth_swarm.xml`
- New config: `config/networks/cyclonedds_local_only.xml`
- Modified: `ros2_ws/src/swarm_bringup/launch/hw_drone.launch.py`,
  `docker/compose.demo.yaml`, `docker/compose.hw.yaml`,
  `config/networks/cyclonedds_drone_template.xml` (marked legacy).

## References

- RFD900x — RFDesign: <https://files.rfdesign.com.au/Files/documents/RFD900x%20DataSheet.pdf>
- SiK firmware — ArduPilot: <https://ardupilot.org/copter/docs/common-3dr-radio-advanced-configuration-and-technical-information.html>
- ADR 0004 — superseded for intra-swarm, retained for GCS edge
- ADR 0008 — leader-follow data path; updated alongside this ADR
