# Architecture Overview

This document is a navigation aid. Authoritative content lives in `PLAN.md` (canonical plan) and the ADRs (`docs/adr/`).

## Read me in this order

1. [`../../PLAN.md`](../../PLAN.md) — stack picks, phased roadmap, risks, verification.
2. [`../adr/0001-ros-humble-jetpack6.md`](../adr/0001-ros-humble-jetpack6.md) — why Humble.
3. [`../adr/0002-mavros-over-ap-dds-for-now.md`](../adr/0002-mavros-over-ap-dds-for-now.md) — why MAVROS.
4. [`../adr/0003-gazebo-harmonic-ardupilot-gz.md`](../adr/0003-gazebo-harmonic-ardupilot-gz.md) — simulator path.
5. [`../adr/0004-cyclone-dds-plus-zenoh-edge.md`](../adr/0004-cyclone-dds-plus-zenoh-edge.md) — comms (intra-swarm half superseded by ADR 0009; Zenoh GCS edge half still in force).
6. [`../adr/0005-fast-lio2-leader-rtabmap-followers.md`](../adr/0005-fast-lio2-leader-rtabmap-followers.md) — SLAM split.
7. [`../adr/0006-yolov8-tensorrt-isaac-ros.md`](../adr/0006-yolov8-tensorrt-isaac-ros.md) — perception.
8. [`../adr/0007-version-pinning-policy.md`](../adr/0007-version-pinning-policy.md) — reproducibility.
9. [`../adr/0008-leader-follow-demo-integration.md`](../adr/0008-leader-follow-demo-integration.md) — leader-follow for the hardware demo.
10. [`../adr/0009-mavlink-radio-supersedes-dds-intra-swarm.md`](../adr/0009-mavlink-radio-supersedes-dds-intra-swarm.md) — SiK/RFD900 radio for inter-drone comms; DDS becomes per-Jetson.

## High-level data flow

```
                                 ┌─────────────────┐
                                 │ Operator (GCS + │
                                 │ Foxglove Studio)│
                                 └────────┬────────┘
                                          │ Zenoh (selective topics) over WiFi
                                          │
                                ┌─────────▼─────────┐
                                │  drone_0 (leader) │  LiDAR · RGB · GPS
                                │  FAST-LIO2 + OctoMap│
                                │  Zenoh router       │
                                │  YOLOv8s            │
                                │  radio_bridge       │
                                └─┬────────────────┬─┘
                                  │ SiK / RFD900x MAVLink radio (ADR 0009)
              ┌───────────┬───────┼───────┬───────────┐
              ▼           ▼       ▼       ▼           ▼
         drone_1      drone_2  drone_3  drone_4
         RGB · GPS    RGB·GPS  RGB·GPS  RGB·GPS
         YOLOv8n      YOLOv8n  YOLOv8n  YOLOv8n
         RTAB-Map     RTAB-Map RTAB-Map RTAB-Map
         radio_bridge radio_bridge ... ...

Each drone:
  ROS 2 Humble (Cyclone DDS bound to `lo`, ROS_DOMAIN_ID = 100 + DRONE_ID)
  MAVROS ↔ ArduPilot (Copter 4.5.x) · robot_localization EKF
  Inter-drone link: radio_bridge over SiK/RFD900x — no shared DDS LAN.
```

**GCS** above is the MAVLink ground station — **Mission Planner** (primary) or
**QGroundControl** (cross-platform alternative). See `PLAN.md` § A.

## Topic taxonomy & QoS

See `PLAN.md` § C and the future `topics.md` reference.

## Phase status

See `WORKFLOW.md` for live phase status and `PLAN.md` § D for the roadmap —
Phases 0-7 plus the **Phase 2.5** hardware-demo milestone (leader-follow swarm).
