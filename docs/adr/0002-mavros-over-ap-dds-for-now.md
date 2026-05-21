# ADR 0002: MAVROS over AP_DDS (for now)

**Status**: accepted · **Date**: 2026-05-21

## Context

ArduPilot ships two paths to ROS 2: classic MAVROS (MAVLink ↔ ROS 2 bridge) and AP_DDS (native ROS 2 publishers/subscribers in the autopilot firmware). v1 made the inverse bet and stubbed an ArduPilot adapter against AP_DDS without ever implementing it.

## Decision

Use **MAVROS** as the ROS 2 ↔ flight-controller bridge in v2.0.0. Hide it behind a `VehicleAdapter` interface so AP_DDS can swap in later without touching swarm logic.

## Rationale

- MAVROS (~1.1k★, mature since 2014) has complete coverage of mission upload/download, parameter get/set, mode change, arming, offboard control, RC override, geofence, gimbal, vision pose, GPS injection. AP_DDS at project start is ~12-18 months behind on mission and parameter APIs.
- QGroundControl, Mission Planner, and every published ArduPilot tutorial assume MAVLink. MAVROS interoperates trivially; AP_DDS requires bespoke tooling.
- The cost of MAVROS is one extra hop per message — acceptable on the LAN side of the stack.

## Consequences

- All ArduPilot integration goes through `swarm_control/mavros_adapter.py`.
- `swarm_control/vehicle_adapter.py` keeps a strict interface — no MAVLink concepts leak above it. When AP_DDS reaches MAVROS parity, a sibling `dds_adapter.py` is the only new file required.
- Revisit annually (or sooner if ArduPilot announces AP_DDS feature parity).
