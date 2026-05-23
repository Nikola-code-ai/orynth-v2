# Radio Link Migration Plan — Cyclone DDS → SiK/RFD900 MAVLink

**Status:** Draft — not yet executed
**Owner:** Nikola
**Phase:** 2.5b (2-drone hardware leader-follow)
**Decision date:** 2026-05-23

---

## 1. Problem & decision

Inter-drone communication moves from WiFi/Cyclone-DDS to SiK/RFD900 MAVLink telemetry radios.

- **WiFi/DDS** stays *only inside* each Jetson (local ROS 2 graph: MAVROS ↔ swarm_server ↔ bridges).
- **All cross-Jetson traffic** moves to MAVLink over RFD900.
- `ROS_DOMAIN_ID` is no longer a shared global. Each Jetson uses its own domain (or `lo`-bound DDS) — this prevents accidental WiFi-DDS bleed if the LAN is still up.

## 2. Chosen architecture: **Centralized command bridge over radio**

Why this over a distributed swarm_server: matches current code (swarm_server already lives only on leader), minimizes refactor risk, and 2-drone bandwidth is trivial for RFD900x.

```
┌──────────────────────────  Leader Jetson  ──────────────────────────┐
│                                                                     │
│   MAVROS(drone_0) ──pose──┐                                         │
│                           ▼                                         │
│   swarm_server ── adapters[0..N-1] ──┬──> setpoints to drone_0      │
│                           ▲          └──> setpoints to drone_K via  │
│                           │                      radio_bridge       │
│                           │                                         │
│   radio_bridge <──────────┤   (publishes follower poses into        │
│      │                    │    /drone_K/mavros/local_position/pose, │
│      ▼                    │    intercepts setpoint_raw/local for    │
│   /dev/ttyUSB_RFD ────────┘    drone_K and ships over radio)        │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                          RFD900 multipoint
                                  │
┌──────────────────────────  Follower Jetson  ────────────────────────┐
│                                                                     │
│   radio_bridge                                                      │
│      │                                                              │
│      ├──> publishes setpoint_raw/local for self                     │
│      ├──> publishes leader pose for any local viz                   │
│      └──< subscribes /drone_K/mavros/local_position/pose,           │
│              ships own pose+state over radio every 100 ms           │
│                                                                     │
│   MAVROS(drone_K) ── FC via /dev/ttyTHS1 @ 921600                   │
└─────────────────────────────────────────────────────────────────────┘
```

## 3. Hardware assumption

- **RFD900 connects to the Jetson, not the FC.** Each Jetson runs `radio_bridge` against an unused USB-UART (e.g. `/dev/ttyUSB_RFD`). Reason: full control of message filtering & encoding from Python without ArduPilot routing-param games. Trade-off: if Jetson dies, radio dies. Acceptable for Phase 2.5b — FC RC override still recovers the airframe.
- RFD900 firmware in **multipoint mode**, leader = base node, follower = remote node, GCS = remote node (added later).

## 4. Message contract over the radio

Custom MAVLink message set (defined in a new dialect `orynth_swarm.xml`):

| Msg ID | Name | Direction | Rate | Payload |
|--------|------|-----------|------|---------|
| 220 | `ORYNTH_DRONE_STATE` | Follower → Leader | 10 Hz | drone_id, pose (x,y,z,yaw ENU), armed, mode, batt%, ekf_ok, ts |
| 221 | `ORYNTH_SETPOINT` | Leader → Follower | 10 Hz | drone_id, target (x,y,z,yaw), reference_age_ms |
| 222 | `ORYNTH_COMMAND` | Leader → Follower | on-demand | drone_id, cmd_enum (TAKEOFF/LAND/ABORT/ARM/DISARM), param_f, seq |
| 223 | `ORYNTH_ACK` | Follower → Leader | on cmd | drone_id, seq, success, message[40] |
| 224 | `ORYNTH_HEARTBEAT` | Both | 2 Hz | drone_id, role (LEADER/FOLLOWER), uptime_s |

Why custom instead of stock `GLOBAL_POSITION_INT` etc.: keeps the dialect compact, lets us include EKF/battery in one packet, and we control the filtering. Stock MAVLink streams would also work but the leader's MAVROS would see two FCs' worth of messages and we'd be writing routing filters anyway.

**Bandwidth check (2 drones):** 10 Hz × ~40 B × 2 directions ≈ 800 B/s ≈ 6.4 kbps. RFD900x at 64 kbps air rate, 60% efficiency → ~38 kbps usable. **~17% utilization.** Fine.

## 5. New components

### 5.1 `radio_bridge` ROS 2 node (new package: `swarm_radio`)

Single Python node, two role modes set by env `RADIO_ROLE=leader|follower`.

**Leader mode:**
- Subscribes: `/drone_K/mavros/setpoint_raw/local` for each follower K (via MavrosAdapter shim or direct subscribe)
- Publishes (locally on leader Jetson): `/drone_K/mavros/local_position/pose`, `/drone_K/mavros/state` — synthesized from received `ORYNTH_DRONE_STATE`. **This is the key trick:** swarm_server's adapters keep working unchanged because the topics they subscribe to are still there, just sourced from the radio.
- Sends `ORYNTH_SETPOINT` whenever swarm_server pushes a new setpoint for a follower
- Sends `ORYNTH_COMMAND` on service calls

**Follower mode:**
- Receives `ORYNTH_SETPOINT` → republishes onto local `/drone_K/mavros/setpoint_raw/local` (MAVROS forwards to FC)
- Receives `ORYNTH_COMMAND` → calls local MAVROS arm/takeoff/land/set_mode services
- Sends `ORYNTH_DRONE_STATE` @ 10 Hz from local MAVROS pose/state/battery
- Sends `ORYNTH_ACK` after each command

### 5.2 New watchdogs

- `radio_bridge` tracks per-peer last-rx timestamp; emits `radio_link_age_s` topic.
- swarm_server's existing `leader_pose_timeout_s` watchdog is now also effectively a radio-link watchdog (the leader pose source on a follower's local viz comes from the radio, and on the leader side the *followers'* synthesized poses age out the same way).
- New watchdog: if **follower** loses radio for > `RADIO_TIMEOUT_S` (default 2.0 s), it commands its FC to **BRAKE/LOITER** locally and disarms after `RADIO_DEAD_S` (default 10 s). Safer than waiting for an external command.

### 5.3 Custom MAVLink dialect

- `external/mavlink_dialects/orynth_swarm.xml` — XML defining 220–224.
- Generated Python at build time via `pymavlink mavgen`.

## 6. Components that DO NOT change

- `MavrosAdapter` (`swarm_control/mavros_adapter.py`) — unchanged. It still talks to local-topic `/drone_K/mavros/*`; the radio_bridge just fills those topics on the leader side instead of WiFi DDS.
- Formation math (`swarm_control/formation.py`) — unchanged.
- Service definitions (`swarm_msgs/srv/*`) — unchanged.
- Leader keyboard teleop — unchanged (still talks to local swarm_server).
- Foxglove bridge / `/swarm/status` — unchanged (lives on leader, GCS reads via Zenoh edge later, or direct on the same WiFi if available).

## 7. SITL strategy

SITL **keeps shared-LAN DDS** for now — it's localhost. We add an optional "simulated radio" mode (UDP loopback with bandwidth/latency injection) later if we need to validate radio failure modes in sim. Not blocking Phase 2.5b.

## 8. File-by-file diff

### New files

| Path | Purpose |
|------|---------|
| `ros2_ws/src/swarm_radio/package.xml` | New ROS 2 package |
| `ros2_ws/src/swarm_radio/setup.py` | Python setup |
| `ros2_ws/src/swarm_radio/swarm_radio/__init__.py` | |
| `ros2_ws/src/swarm_radio/swarm_radio/radio_bridge_node.py` | Main bridge node |
| `ros2_ws/src/swarm_radio/swarm_radio/radio_link.py` | RFD900 serial I/O + MAVLink encode/decode |
| `ros2_ws/src/swarm_radio/swarm_radio/dialect.py` | Generated MAVLink dialect loader |
| `ros2_ws/src/swarm_radio/test/test_radio_link.py` | Unit tests (encode/decode round-trip, watchdog) |
| `external/mavlink_dialects/orynth_swarm.xml` | Custom MAVLink dialect |
| `external/mavlink_dialects/README.md` | Dialect generation instructions |
| `docs/adr/0009-mavlink-radio-supersedes-dds-intra-swarm.md` | New ADR superseding 0004 for intra-swarm |
| `docs/runbooks/radio_link_bringup.md` | RFD900 firmware + udev + bringup runbook |

### Modified files

| Path | Change |
|------|--------|
| `ros2_ws/src/swarm_bringup/launch/hw_drone.launch.py` | Add `radio_bridge` node. Switch `ROS_DOMAIN_ID` to per-drone unique (DRONE_ID + 100). Drop `CYCLONEDDS_URI` reference. |
| `ros2_ws/src/swarm_bringup/launch/sitl_swarm.launch.py` | Unchanged for SITL DDS-on-loopback, but add comment noting hardware uses radio_bridge. |
| `docker/compose.demo.yaml` | Replace `network_mode: host` with per-drone bridge net; remove `CYCLONEDDS_URI`; set `ROS_DOMAIN_ID=$((100+DRONE_ID))`; add `/dev/ttyUSB_RFD` device passthrough; add `RADIO_ROLE`. |
| `docker/compose.hw.yaml` | Same env changes as compose.demo.yaml. |
| `config/networks/cyclonedds_drone_template.xml` | Strip peer list; keep DDS bound to `lo` only. Mark as legacy-with-WiFi-fallback. |
| `config/networks/cyclonedds_local_only.xml` | **NEW** — DDS on `lo` only, no multicast peers. Becomes the default. |
| `Makefile` | Add `radio-up`, `radio-down`, `radio-status` targets. Update `demo-up` to source radio config. |
| `swarm_gazebo_keyboard.txt` | Note that this is SITL-only; add pointer to radio runbook for hardware. |
| `docs/adr/0004-cyclone-dds-plus-zenoh-edge.md` | Mark **Superseded by ADR 0009** for intra-swarm scope. Zenoh GCS-edge half remains valid. |
| `docs/adr/0008-leader-follow-demo-integration.md` | Update "Data path" section: leader pose source for follower-local viz is now radio, not DDS. Watchdog section: add radio-link timeout. |
| `docs/runbooks/jetson_swarm_operations.md` | Replace WiFi-LAN topology diagram with radio topology. Update bringup checklist. Replace DDS troubleshooting section with radio troubleshooting. |
| `docs/runbooks/first_flight.md` | Add radio-link pre-flight check, abort behavior on radio loss. |
| `docs/runbooks/bringup_sequence/README.md` | Update sequence diagrams: radio_bridge starts before swarm_server. |
| `docs/runbooks/sitl_swarm_dev.md` | Note: SITL still uses DDS-on-loopback; radio path is hardware-only for now. |
| `docs/architecture/overview.md` | Update inter-drone link description; link to ADR 0009. |
| `README.md` (if exists) | Brief note: radio-based inter-drone link. |

### Untouched (verified safe)

- All `swarm_msgs/srv/*` and `swarm_msgs/msg/*` — wire format stays.
- `swarm_control/swarm_server_node.py` core loop — runs untouched on leader.
- `swarm_control/mavros_adapter.py` — unchanged.
- `swarm_control/formation.py` — unchanged.
- All keyboard / GCS / Foxglove plumbing.
- ArduPilot params (no SERIAL routing changes since radio is on Jetson side).

## 9. Execution order

1. Create `swarm_radio` package skeleton + dialect XML + dialect loader. Verify dialect builds.
2. Implement `radio_link.py` (serial I/O, encode/decode, framing). Unit tests for round-trip.
3. Implement `radio_bridge_node.py` leader mode + follower mode. Mock serial in tests.
4. Wire into `hw_drone.launch.py`. Validate launch builds (no FC needed yet).
5. Update Docker compose + Makefile + DDS local-only config.
6. Write ADR 0009; mark ADR 0004 superseded-in-part; update ADR 0008.
7. Update runbooks (`jetson_swarm_operations`, `first_flight`, `bringup_sequence`, `sitl_swarm_dev`, architecture/overview, new `radio_link_bringup`).
8. Update `swarm_gazebo_keyboard.txt` to clarify SITL-only.
9. Smoke test: `colcon build --packages-select swarm_radio swarm_bringup` + run unit tests.

## 10. Out of scope (deliberately)

- Real RFD900 hardware bench-up — that's a separate runbook the operator follows after this lands.
- GCS over radio — GCS link stays as-is (WiFi or its own RFD900 later). ADR 0004's Zenoh-edge plan is intact for the GCS half.
- Mesh / 3-drone+ scaling — works the same; just add more follower peers in dialect.
- Drone-to-drone collision avoidance via radio — separate workstream.
- BRAKE-on-radio-loss tuning (RADIO_TIMEOUT_S, RADIO_DEAD_S) — defaults shipped; tune on-airframe.

## 11. Rollback

- All changes additive except `compose.demo.yaml` network mode and DDS peer list. Keep `config/networks/cyclonedds_drone_template.xml` in repo as legacy; revertable via `git revert` of the compose change.
- `swarm_radio` package can be disabled by not launching `radio_bridge` — swarm_server then has no follower data and idles safely.
