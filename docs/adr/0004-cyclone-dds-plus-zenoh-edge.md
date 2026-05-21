# ADR 0004: Cyclone DDS intra-swarm + Zenoh on the WAN edge

**Status**: accepted · **Date**: 2026-05-21

## Context

Two distinct communication regimes exist:

1. **Intra-swarm LAN** — 5 drones + GCS on the same 802.11ac network. Low loss, moderate bandwidth, no NAT.
2. **Drone-to-GCS link** — same physical medium but treated as WAN-like: lossy at range, may need store-and-forward, must not multicast (WiFi APs drop it).

A single ROS 2 RMW cannot serve both well. v1 punted by exposing an env var (`ORYNTH_RMW`) to choose Cyclone or Zenoh globally — a workaround, not a design.

## Decision

- **Intra-swarm**: Eclipse **Cyclone DDS** (`rmw_cyclonedds_cpp`) on every node.
  - Drone-internal: SHM + loopback multicast.
  - Drone-to-drone LAN: explicit peer-list discovery via `config/networks/cyclonedds_drone_<N>.xml`.
- **Edge (leader → GCS)**: **Zenoh router** on the leader running `zenoh-plugin-ros2dds`, configured to forward a curated topic allowlist.

## Rationale

- Cyclone DDS (~900★) is the standard ROS 2 alternative RMW; lower memory footprint than Fast DDS, recommended by Open Robotics for embedded targets.
- Zenoh (~5.4k★) handles WAN-style links natively (selective forward, store-and-forward, congestion-aware) — exactly what 5 drones flying over 100+ m WiFi need.
- Running the entire stack on `rmw_zenoh` is tempting but the implementation is Tier-3 and observed-unstable under sustained load (ROSCon 2024 evaluations). Cyclone is Tier-1.

## Consequences

- The leader doubles as the swarm's outbound gateway. Acceptable: leader has the LiDAR and is the canonical map source anyway.
- GCS never sees raw DDS discovery from the swarm — it sees a single Zenoh endpoint.
- Followers cannot directly publish to the GCS; they publish locally and the bridge routes selectively. This is a feature: it enforces a bandwidth budget at the routing layer.
- `config/networks/zenoh_uplink.json5` is the authoritative topic allowlist.
