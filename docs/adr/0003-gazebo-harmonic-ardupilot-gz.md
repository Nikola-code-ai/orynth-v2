# ADR 0003: Gazebo Harmonic + ardupilot_gz

**Status**: accepted · **Date**: 2026-05-21

## Context

v1 used Gazebo Fortress, paired with Aerostack2's drone models. The simulator and the real flight stack diverged: SITL flew Aerostack2 controllers; hardware would fly ArduPilot. v2 must close that gap — the simulator should run the exact same firmware binary path as the Pixhawk.

## Decision

- Simulator: **Gazebo Harmonic** (LTS, supported through Sep 2028).
- Bridge: official **`ardupilot_gazebo`** plugin (under the `ardupilot/ardupilot_gz` umbrella).
- World/model assets: from `ardupilot_gz` defaults, extended with `worlds/search_field.sdf`.

## Rationale

- Gazebo Harmonic is the current Open Robotics LTS and the version `ardupilot_gz` actively tracks. Fortress is in deprecation phase; Garden is older Harmonic-track.
- `ardupilot_gazebo` lets a single SITL binary connect to Gazebo via Gazebo Transport, with first-class multi-instance support (`--instance N`).
- The same `arducopter` binary used in SITL is built from the same source tree as the Pixhawk firmware. No simulator-specific control plane.

## Consequences

- v1 sensor/world configs are not portable; v2 starts a fresh `worlds/` directory.
- SITL bringup is one process per drone (5 `arducopter` instances + 1 Gazebo). Resource budget on a 16-core dev workstation: comfortably fits.
- AirSim, jMAVSim, gz-classic explicitly rejected — none match ArduPilot's official sim path.
