# ADR 0005: FAST-LIO2 on leader, RTAB-Map on followers

**Status**: accepted · **Date**: 2026-05-21

## Context

Sensor topology is heterogeneous by design:

- `drone_0` (leader): 360° LiDAR + IMU + GPS + RGB camera.
- `drone_1..4` (followers): IMU + GPS + RGB camera. No LiDAR.

Map quality and per-drone localization both matter. A single SLAM stack that works on both is unrealistic — LiDAR-IMU SLAM and visual SLAM solve different problems.

## Decision

- **Leader**: **FAST-LIO2** (HKU-MARS) for tightly-coupled LiDAR-IMU odometry. **OctoMap** for 3D occupancy from registered clouds.
- **Followers**: **RTAB-Map** in monocular+IMU+GPS-prior mode.
- **Coordinate anchor**: all SLAM frames anchored to GPS-derived ENU via `robot_localization` EKF on each drone.
- **Map authority**: the leader's OctoMap is the canonical 3D map. Followers contribute *semantic overlay* (geolocated detections) only.

## Rationale

- FAST-LIO2 (~3.9k★) is the fastest published tightly-coupled LIO and runs >20 Hz on Orin Nano. Loop closure isn't critical with GPS available.
- RTAB-Map (~2.6k★) has an actively-maintained ROS 2 wrapper, BSD license, and supports monocular+IMU+GPS priors. ORB-SLAM3 has no maintained ROS 2 wrapper and is GPLv3 (complicates Docker distribution).
- Letting followers contribute map geometry creates registration/drift problems that have no good solution at this scale. Letting them contribute *labels* into the leader's map is well-defined.

## Consequences

- Map merging logic is simpler than v1's roadmap implied: geolocate detection → OctoMap voxel coords → annotate. No multi-source ICP.
- If the leader is lost mid-flight, the swarm has no live 3D map. Mitigation: leader's last OctoMap is checkpointed every 10 s to the GCS and is recoverable.
- Followers do generate visual landmarks (used for their own local TF), they just don't push to the shared map. Their RTAB-Map databases are archived per-flight for offline analysis.
- LiDAR is GPLv3? Check FAST-LIO2 license at scaffold time — currently GPLv2. Mitigation: run FAST-LIO2 as a separate process, communicate via ROS topics — no source-level linking, no GPL contamination of v2 code.
