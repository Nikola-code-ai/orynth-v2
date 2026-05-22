# Orynth v2 — Comprehensive Implementation Plan

> **Status**: approved 2026-05-21. Canonical plan for the v2 rewrite. Edit via PR with rationale in commit message.

## Context

A working but architecturally compromised 5-drone swarm prototype exists at `../aerolab_ws` (v1, Aerostack2-based). The real hardware is **ArduPilot-based flight controllers + 5x Jetson Orin Nanos**. v1's stack mismatch produced two parallel sim tracks (one working, one stubbed), an ADR documenting the split, an empty perception package, no CI, no version pinning, no SLAM, and a research-grade ecosystem with a small community.

**Goal**: build `v2/` replacing every component with the most widely-adopted, ArduPilot-native open-source equivalent — judged by GitHub stars, official ArduPilot/ROS endorsements, and community maturity. Mission: **outdoor search-and-rescue with human detection priority** (GPS available, LiDAR on leader, RGB cameras on followers).

**Hard requirements**: ROS 2, Docker, YOLO. Everything else picked for industry-standard fit.

---

## v1 Mistakes Being Corrected

| # | v1 mistake | v2 fix |
|---|---|---|
| 1 | Aerostack2 sim, ArduPilot hardware → two sim tracks | ArduPilot SITL + Gazebo Harmonic + `ardupilot_gazebo`. Sim runs the same firmware binary path as hardware. |
| 2 | Perception scaffold sat empty for months (no `package.xml`) | `swarm_perception` ships in Phase 0 with a passthrough detector; Phase 3 swaps in YOLOv8. |
| 3 | No CI/CD despite 21 unit tests | GitHub Actions: lint + unit on every PR, SITL smoke on PR + nightly. |
| 4 | Floating apt versions, no pinning | Docker images by SHA256 digest, apt by `pkg=version`, pip with `--require-hashes`, ROS via vcstool `.repos` with git SHAs, model weights via Git LFS + SHA manifest. |
| 5 | Aerostack2 lock-in (research-grade, small community) | MAVROS + Mission Planner / QGC + ardupilot_gz (industry-standard ArduPilot ecosystem). |
| 6 | No SLAM/3D mapping | FAST-LIO2 on leader, RTAB-Map on followers, OctoMap for occupancy — from Phase 4. |
| 7 | Single GCS (Foxglove only) lost MAVLink-native tooling | Mission Planner / QGC for safety/MAVLink ops + Foxglove for ROS 2 viz. Roles separated. |

---

## A. Stack Selection

One pick per slot, industry-standard, justified by community size and official endorsements.

| Slot | Pick | Why over alternatives |
|---|---|---|
| ROS 2 distro | **Humble Hawksbill (LTS)** | Tier-1 on Ubuntu 22.04 = JetPack 6 = Orin Nano; LTS through May 2027; every ArduPilot integration tests against it. Jazzy needs Ubuntu 24.04 (no JetPack yet). |
| Flight stack | **ArduPilot Copter 4.5.x** | Matches hardware. Pinned tag, not master. |
| Simulator | **Gazebo Harmonic + `ardupilot_gazebo`** | Current LTS, recommended by Open Robotics and ArduPilot's `ardupilot_gz` repo. Supported through Sep 2028. Multi-instance SITL is first-class. |
| MAVLink ↔ ROS bridge | **MAVROS** (`mavlink/mavros`, ~1.1k★) | De-facto standard. AP_DDS still ~12-18 months behind on mission/parameter APIs. `VehicleAdapter` abstraction keeps AP_DDS swap path open. |
| DDS (intra/LAN) | **Cyclone DDS** (`eclipse-cyclonedds`, ~900★) | Lower memory than Fast DDS; recommended alternative RMW. |
| DDS edge (WAN) | **Zenoh** via `zenoh-plugin-ros2dds` (~5.4k★) | Selective topic forwarding, store-forward over lossy WiFi. Used only on leader-to-GCS link. |
| GCS (MAVLink) | **Mission Planner 1.3.80+** · **QGroundControl 4.4+** (~3.4k★) | Mission Planner — ArduPilot's first-party reference GCS, **primary**: deepest Copter parameter/calibration coverage + a built-in Swarm screen (ADR 0008). QGC — the cross-platform (Linux/macOS) **alternative**. Either owns arming, parameters, missions, geofence, RTL. |
| GCS (ROS) | **Foxglove Studio 2.x** (~1.6k★) | Modern ROS 2 visualization. Owns mission/perception view. |
| Mission protocol | **MAVLink Mission Protocol via MAVROS `WaypointPush`** | No MAVSDK on top — overlap and bloat. |
| Swarm orchestration | **BehaviorTree.CPP** (~3.2k★) + Crazyswarm2 patterns | Same BT engine Nav2 uses; Groot2 GUI. Crazyswarm2 architecture adapted from CFlib to MAVROS. |
| LiDAR-IMU SLAM (leader) | **FAST-LIO2** (~3.9k★) | Fastest tightly-coupled LIO; runs >20 Hz on Orin Nano. |
| 3D occupancy | **OctoMap** (~2.0k★) | Standard 3D occupancy grid; Nav2-consumable. |
| Visual SLAM (followers) | **RTAB-Map** (~2.6k★) | Official ROS 2 wrapper, BSD license, online-capable, GPS-prior support. ORB-SLAM3 has no maintained ROS 2 wrapper and is GPLv3. |
| Navigation | **Nav2** (~2.8k★) + **Ego-Planner-v2** (~1.4k★) for 3D | Nav2 ships Phase 5; Ego-Planner Phase 6. |
| Computer vision | **YOLOv8n/s** (Ultralytics, ~30k★) **+ TensorRT + `isaac_ros_yolov8`** | YOLO is hard req. Ultralytics canonical. Isaac ROS gives 30+ FPS on Orin Nano. |
| Sensor fusion | **`robot_localization` EKF** + ArduPilot EKF3 onboard | Don't fight EKF3. `robot_localization` fuses MAVROS odom + visual odom. |
| Containerization | **Docker + Compose, `docker buildx` multi-arch (amd64+arm64)** | ARM64 uses `nvcr.io/nvidia/l4t-jetpack:r36.3.0` for CUDA/TensorRT prebuilt. |
| CI | **GitHub Actions**: lint, unit, sitl_smoke, docker_build, release | SITL smoke <8 min. |
| Telemetry/logging | **rosbag2 (mcap)** + ArduPilot DataFlash | mcap is Humble default and Foxglove-native; 30% smaller than sqlite3. |

---

## B. Repository Layout

```
v2/
├── README.md, PLAN.md, LICENSE
├── .gitignore, .gitattributes (LFS for *.pt, *.engine, *.pcd)
├── .pre-commit-config.yaml, .dockerignore
│
├── docker/
│   ├── base.Dockerfile                 # ROS 2 Humble + common deps (multi-arch)
│   ├── dev.Dockerfile                  # +dev tools
│   ├── runtime.amd64.Dockerfile        # slim, workstation/SITL
│   ├── runtime.arm64.Dockerfile        # FROM nvcr l4t-jetpack:r36.3.0
│   ├── sitl.Dockerfile                 # ArduPilot SITL + Gazebo Harmonic
│   ├── gcs.Dockerfile                  # Mission Planner/QGC + Foxglove + Zenoh
│   ├── compose.{dev,swarm,hil,field}.yaml
│   └── digests.lock                    # SHA256s of all base images
│
├── ros2_ws/src/
│   ├── swarm_msgs/                     # custom msg/srv/action defs
│   ├── swarm_bringup/                  # launch files, worlds, per-drone params
│   ├── swarm_control/                  # VehicleAdapter, MavrosAdapter, formation, controller, server
│   ├── swarm_behaviors/                # BehaviorTree.CPP plugins + XML trees
│   ├── swarm_perception/               # YOLO detector + geolocator (ships Phase 0)
│   ├── swarm_mapping/                  # FAST-LIO2, RTAB-Map, OctoMap, map_merge
│   ├── swarm_navigation/               # Nav2 params + 3D planner integration
│   ├── swarm_gcs/                      # Foxglove bridge, bandwidth manager, telemetry agg
│   ├── swarm_sim/                      # ardupilot_gz wrappers, SITL launcher
│   └── swarm_hardware/                 # arm64-only; Jetson bringup, udev, sensors
│
├── config/
│   ├── ardupilot_params/               # per-airframe .parm dumps
│   ├── mission_templates/              # MAVLink .plan files
│   ├── networks/                       # CycloneDDS XML + Zenoh router configs
│   └── models/manifest.yaml            # YOLO model SHA256 + URL
│
├── scripts/
│   ├── bringup/{sitl_swarm,demo_swarm,field_swarm,hil}.sh
│   ├── calibration/{compass,esc,accel}.sh
│   ├── log_analysis/{rosbag_to_csv,dataflash_to_kml}.py
│   ├── build/{build_workspace,build_yolo_tensorrt}.sh
│   └── ci/{run_sitl_smoke,wait_for_mavros}.sh
│
├── docs/
│   ├── architecture/{overview,topics,namespacing,dataflow.svg}
│   ├── adr/0001-0008.md
│   ├── runbooks/{first_flight,sitl_swarm_dev,hil_test,field_deploy,emergency}.md
│   ├── hardware/{bom,wiring,calibration,airframe_setup}.md
│   └── ci/{pipeline,smoke_test_spec}.md
│
└── .github/workflows/{lint,unit,sitl_smoke,docker_build,release}.yml
```

ADRs (0001-0007 locked in from day one; 0008 added at the Phase 2.5 milestone):

1. ROS Humble on JetPack 6
2. MAVROS over AP_DDS (for now)
3. Gazebo Harmonic + ardupilot_gz
4. Cyclone DDS intra + Zenoh edge
5. FAST-LIO2 (leader) + RTAB-Map (followers)
6. YOLOv8 + TensorRT + Isaac ROS
7. Version-pinning policy
8. Leader-follow integration for the hardware demo

---

## C. Communication Architecture

**Namespacing**: every drone owns `/drone_<N>` (N=0..4). `drone_0` is the leader (LiDAR). Shared domain `ROS_DOMAIN_ID=42`. Swarm-wide topics at root: `/swarm/status`, `/swarm/command`, `/tf_static`.

**TF tree**: `earth (ENU) → map → drone_<N>/odom → drone_<N>/base_link → sensor_frames`.

**Topic taxonomy & QoS**:

| Category | Pattern | QoS |
|---|---|---|
| State | `/drone_<N>/mavros/state`, `/mavros/global_position/global`, `/odom` | RELIABLE, KEEP_LAST 5 |
| Command | `/drone_<N>/mavros/setpoint_position/local`, `/swarm/command` | RELIABLE, KEEP_LAST 1 |
| Perception | `/drone_<N>/perception/detections`, `/camera/image_raw/compressed` | RELIABLE (det), BEST_EFFORT (img) |
| Mapping | `/drone_0/lio/odom`, `/lio/cloud_registered`, `/octomap_full`, `/drone_<N>/rtabmap/map_data` | RELIABLE, transient_local for static maps |
| Swarm | `/swarm/status`, `/swarm/formation`, `/swarm/leader_pose` | RELIABLE, KEEP_LAST 5 |
| Logging | `/diagnostics`, `/rosout` | BEST_EFFORT |

**Bandwidth strategy** (5 drones × 802.11ac, ~50 Mbps usable):

- Always-on per drone: telemetry @ 10 Hz, state @ 5 Hz, detections @ 5 Hz, 320×240 JPEG thumbnail @ 2 FPS. ~150 KB/s × 5 = 6 Mbps total.
- Selective high-res: only operator-selected drone streams 1080p H.264 @ 15 FPS (~4 Mbps). Switched via `/gcs/active_stream`; `bandwidth_manager_node` gates republishers.
- LiDAR cloud: leader-only, never raw — downsampled OctoMap diff @ 1 Hz (~500 KB/s).

**Discovery**:

- Intra-drone: SHM + multicast on `lo`.
- Drone-to-drone (LAN): Cyclone DDS with explicit peer lists per drone (WiFi APs drop multicast). XML configs per drone in `config/networks/`.
- Drone-to-GCS: only via Zenoh bridge on the leader (swarm's outbound gateway). GCS subscribes selectively through Zenoh, never sees raw DDS.

---

## D. Phased Roadmap with Acceptance Gates

### Phase 0 — Repo Scaffold + CI + Docker Baseline (Week 1)

- **Deliverables**: full directory tree; multi-arch `base.Dockerfile`; `lint.yml` + `unit.yml` green; `.repos` pinning every external git dep by SHA; pre-commit hooks; ADRs 0001-0007 drafted; `swarm_perception` with a passthrough detector.
- **Acceptance**: `docker buildx build --platform linux/amd64,linux/arm64 -f docker/base.Dockerfile .` succeeds; `colcon build && colcon test` passes; fresh-clone-to-dev-container in <10 min.
- **CI gate**: lint + unit required.

### Phase 1 — Single-Drone ArduPilot SITL + MAVROS + Foxglove (Week 2-3)

- **Deliverables**: `sitl.Dockerfile`; `compose.dev.yaml` runs SITL + MAVROS + Foxglove bridge + Studio; `mavros_adapter.py` implementing `VehicleAdapter` (ported from v1); `sitl_single.launch.py`.
- **Acceptance**: cold-start `docker compose up` <60 s, arm, GUIDED takeoff to 5 m, waypoint to (10,0,5), land; Foxglove shows live pose + camera. Logged as `accept/phase1.mcap`.
- **CI gate**: headless `sitl_smoke.yml` runs in <8 min on every PR.

### Phase 2 — 5-Drone SITL Swarm + Diamond Formation (Week 4-5)

- **Deliverables**: `sitl_launcher.py` spawning N ArduPilot SITL instances at offset spawn points with per-instance ports (`5760+N*10` master, `14550+N*10` UDP); 5 namespaced MAVROS instances; `swarm_server_node` exposing `/swarm/takeoff`, `/swarm/land`, `/swarm/engage_formation`, `/swarm/<id>/manual_goto`; formation math ported from v1, implemented **reference-agnostic** — a static centroid for the diamond hold, while the same code accepts a live leader pose at the Phase 2.5 demo (ADR 0008).
- **Acceptance**: simultaneous 5-drone takeoff, diamond hold 60 s with <0.5 m mean horizontal drift per follower, coordinated land. `operator.json` Foxglove layout shows all 5.
- **CI gate**: 5-drone smoke nightly; PR CI stays single-drone for budget.

### Phase 2.5 — Leader-Follow Demo (Milestone, after Phase 2)

A deliberately minimal vertical slice proving the swarm works as a leader-follow system: an operator manipulates the **leader** (`drone_0`) and the **followers** autonomously hold a diamond relative to the leader's *live* pose, tracking it as it moves. Mapping, computer vision, and autonomous search are explicitly **post-demo** (Phases 3-5, unchanged). The milestone runs in **two stages — proven in SITL first (2.5a), then flown on hardware (2.5b)** — so no real airframe ever flies a behaviour the simulator has not already shown.

- **Integration** (ADR 0008): followers fly **GUIDED**, commanded by `swarm_server_node` streaming position setpoints through `MavrosAdapter`; the formation reference is the leader's *live* MAVROS pose rather than a static centroid — a small generalization of Phase 2's `formation.py`. ArduPilot's native **FOLLOW mode** (`FOLL_SYSID` / `FOLL_OFS_*`) is the documented fallback if ROS-side tracking proves jittery. The integration is identical for both stages — only the vehicles differ (SITL vs real airframes).

#### Phase 2.5a — Leader-Follow SITL Rehearsal

Proves leader-follow in the Gazebo swarm sim (Phase 2's stack), before any hardware flies. The operator "flies" the leader in simulation; the four followers shadow it in a live diamond.

- **Deliverables**:
  - `swarm_control` live-reference formation mode — `swarm_server_node` gains `/swarm/follow_leader` (engage/disengage), whose control loop reads the leader's *live* pose every tick instead of the static centroid `/swarm/engage_formation` captures; `formation.py` is already reference-agnostic (Phase 2).
  - follower-side **leader-pose watchdog** — a stale leader pose makes a follower hold position / fall back to LOITER.
  - a sim leader-input path — the operator moves `drone_0` via `/swarm/drone_0/manual_goto` (or RC-into-SITL) and the followers track it.
- **Acceptance**: in the `compose.swarm` Gazebo sim, the operator moves the leader and the four followers track the diamond live with <0.5 m mean horizontal error; the watchdog demonstrably holds a follower on a simulated leader-pose dropout. Recorded as `accept/leaderfollow_sitl.mcap`.
- **CI gate**: optional extension of the nightly `sitl-5-drone-swarm` job.

#### Phase 2.5b — Hardware Demo

The first **on-hardware** flight — the same leader-follow on real airframes. It pulls a hardware flight ahead of the planned HIL phase (Phase 6), so a condensed safety gate is a hard prerequisite.

- **Deliverables**:
  - `scripts/bringup/demo_swarm.sh` — hardware bringup; blocks until the leader and every follower report healthy EKF, GPS lock, battery >90%.
  - `config/ardupilot_params/` — per-airframe demo params: geofence, RC-loss failsafe, GUIDED tuning, distinct `MAV_SYSID` per drone.
  - `docs/runbooks/first_flight.md` — demo flight runbook: roles (one safety pilot per drone, RC override armed), preflight, abort triggers, formation spacing.
  - `demo.json` Foxglove layout — leader + follower poses and live per-follower formation error.
- **Prerequisite — condensed safety gate** (cleared before any motor spins): **Phase 2.5a passed in SITL**; per-airframe compass/accel calibration; props-off GUIDED arm test per drone; geofence + RC-loss failsafe verified via Mission Planner / QGC (a subset of the Phase 6 HIL checklist); single-drone manual hover for the leader and each follower individually before any formation flight.
- **Acceptance**: outdoors, open area, ≥5 m formation spacing. Leader manually piloted (LOITER/POSHOLD) by a safety pilot; ≥2 followers (target 4) autonomously take off, form up, and track the manually-moved leader for ≥60 s of leader motion with mean horizontal formation error <2 m per follower (looser than the 0.5 m SITL gate — hardware GPS without RTK, wind, first flight); the leader-pose watchdog demonstrably holds a follower on a simulated link drop; coordinated land, all disarm. Recorded as `accept/demo_leaderfollow.mcap` + flight video.
- **Sign-off**: no CI gate (hardware). Safety-pilot + maintainer sign-off on the `first_flight.md` checklist; demo footage attached to the milestone.

### Phase 3 — YOLO Human Detection + Isaac ROS Pipeline (Week 6-7)

- **Deliverables**: `yolo_detector_node.py` (Isaac ROS on Jetson, plain Ultralytics fallback for x86/CI); `yolov8n_human.engine` via Git LFS; `detection_geolocator_node` projects bboxes → world coords using intrinsics + pose + flat-ground assumption; `perception.json` Foxglove layout.
- **Acceptance**: in `worlds/search_field.sdf` (actors = humans), each drone publishes `/drone_<N>/perception/detections` ≥15 Hz, recall ≥0.7 at simulated 50 m altitude, geolocation error <3 m.
- **CI gate**: unit test on static image. SITL smoke adds: spawn actor, drone_1 publishes detection within 30 s of takeoff.

### Phase 4 — LiDAR Mapping (FAST-LIO2 + OctoMap) (Week 8-9)

- **Deliverables**: leader Gazebo model gets simulated 360° LiDAR; `leader_lio.launch.py` runs FAST-LIO2; OctoMap server consumes registered cloud; `mapping.json` Foxglove layout.
- **Acceptance**: leader flies 50×50 m boustrophedon at 10 m AGL in SITL, produces coherent 0.5 m-resolution OctoMap; LIO odom drift <2 m over 5 min before GPS fusion.
- **CI gate**: nightly only. `tools/map_quality_check.py` asserts ground-plane coverage >80%.

### Phase 5 — Autonomous Search + Nav2 (Week 10-11)

- **Deliverables**: `search_and_rescue.xml` BT: takeoff → diamond → boustrophedon over operator polygon → on detection, leader breaks formation, hovers over geolocated position, calls followers, signals operator → RTL. Per-drone Nav2 for local avoidance using leader's OctoMap (shared via Zenoh). Missions editable via Mission Planner / QGC waypoint upload; follower patterns auto-generated.
- **Acceptance**: in `search_field.sdf` with 3 humans hidden in 100×100 m polygon, swarm finds ≥2 in <5 min and converges.
- **CI gate**: nightly headless run, assert detection count ≥2.

### Phase 6 — Hardware-in-the-Loop (Week 12-13)

- **Deliverables**: `compose.hil.yaml` (1 real Jetson + FCU, 4 SITL); `jetson_bringup.launch.py`; bench airframe params in `config/ardupilot_params/`; calibration scripts.
- **Acceptance**: bench protocol — props OFF, real FCU GUIDED-armed, swarm commands take effect, real IMU/GPS published, YOLO on real Jetson camera ≥15 FPS, thermal <80°C for 30 min. Documented in `docs/runbooks/hil_test.md`.
- **CI gate**: manual sign-off checklist in PR template.

### Phase 7 — Full 5-Drone Field Deployment (Week 14-16)

- **Deliverables**: `compose.field.yaml`; field-grade Zenoh config; preflight automation (`field_swarm.sh` blocks until all 5 report healthy EKF, GPS lock, battery >90%); rosbag archival; tlog + DataFlash collection.
- **Acceptance**: outdoor coordinated takeoff to 10 m AGL, 2-min diamond hold, 100×100 m search pattern (no human targets first flight, just pattern + RTL), coordinated land. Recorded as `accept/phase7_field.mcap`.
- **CI gate**: none; tag `v2.0.0` on green field flight.

---

## E. Verification Strategy

- **Unit tests** (`colcon test`, 70% line coverage Python / 60% C++):
  - `swarm_control`: formation math (ported + extended), adapter contract, controller state machine.
  - `swarm_perception`: YOLO on fixed image; geolocator hand-computed cases.
  - `swarm_mapping`: OctoMap insertion on synthetic clouds.
  - `swarm_behaviors`: each BT plugin with mocked services.
- **SITL integration**:
  - PR smoke: 1 drone, arm/takeoff/land, 8 min budget.
  - Nightly: 5 drones, full search mission against fixture world.
  - `scripts/ci/run_sitl_smoke.sh` uses `pexpect` to drive compose + assert log lines + clean teardown.
- **Leader-follow demo** (Phase 2.5): proven in SITL first — **2.5a**, the operator moves the leader in the Gazebo swarm and the four followers track the diamond live (<0.5 m) — then flown on hardware — **2.5b**, the first on-hardware flight, behind a condensed safety gate (per-airframe calibration, props-off GUIDED arm, geofence + RC-loss failsafe; a subset of the Phase 6 HIL checklist). `docs/runbooks/first_flight.md` checklist; safety-pilot sign-off. Not in CI.
- **HIL bench** (Phase 6+): `docs/runbooks/hil_test.md` checklist — power order, telemetry verify, GUIDED arm props-off, RC override <100 ms, failsafe on RC loss, thermal soak. Safety pilot sign-off required.
- **Field** (Phase 7+): `docs/runbooks/field_deploy.md` — site survey, RF check, geofence via Mission Planner / QGC, sequential bringup (drone_0 first), 3 m hover per drone before formation, hard-abort triggers documented.

---

## F. Reusable Artifacts From v1

| v1 file | Verdict | Action |
|---|---|---|
| `swarm_api.py` | **Port verbatim** | Move to `swarm_control/`. Add `PlatformProfile.ARDUPILOT_HARDWARE`. |
| `vehicle_adapter.py` | **Port verbatim** | Interface unchanged. |
| `formation.py` | **Port + extend** | Add line, V, circle, search-spread layouts. |
| `swarm_controller.py` | **Refactor** | Strip AS2 imports; adapter factory at construction; MAVROS service-availability check. |
| `swarm_command_node.py` | **Refactor** | Keep dispatcher pattern. Typed `swarm_msgs/SwarmStatus` replaces JSON String. |
| `as2_adapter.py` | **Abandon** | Replaced by `mavros_adapter.py`. |
| `ardupilot_adapter.py` | **Abandon** | Stub-only. |
| `flock_orchestrator.py` | **Refactor lightly** | Repoint at MAVROS adapter + namespaced services. |
| `tf_static_bridge.py` | **Abandon** | MAVROS publishes TF directly. |
| `test/test_swarm_components.py` | **Port verbatim** | Pure types/geometry, no ROS deps. |
| `test/test_swarm_controller.py` | **Refactor** | Reuse FakeAdapter scaffolding; rewrite assertions. |
| `bandwidth_manager_node.py` | **Refactor** | Same architecture; rewrite against new active-stream topic. |
| `telemetry_aggregator_node.py` | **Refactor** | Swap AS2 telemetry source for MAVROS aggregation. |
| `swarm_markers_node.py` | **Port verbatim** | Topic-agnostic marker publisher. |
| `aerolab_perception/*` | **Abandon** | Empty. New `swarm_perception` from scratch. |
| `docs/adr/0001-hybrid-control-stack.md` | **Supersede** | v2 ADRs 0001-0007 replace it. |
| `Dockerfile` | **Abandon** | AS2-coupled. New multi-stage role-specific Dockerfiles with pinned digests. |

~600 LOC ported (≈30% of v1's Python) — the platform-neutral logic.

---

## G. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| **Orin Nano thermal/power under load** | TensorRT INT8 YOLOv8n; `nvpmodel -m 0` MAXN at bringup; active cooling in BoM; 30-min thermal soak in Phase 6; followers can drop mapping if margin tight. |
| **Wireless link saturation** | Always-on @ ~12% of 50 Mbps; Zenoh selective forwarding via leader-only WAN link; QoS prioritizes telemetry; adaptive bitrate based on RSSI; field tests expand range incrementally. |
| **ArduPilot SITL port collisions** | Deterministic port blocks: `5760+N*10` master, `14550+N*10` UDP; `SYSID_THISMAV=N+1` per instance; integration test verifies 5 distinct heartbeats before declaring ready. |
| **Heterogeneous SLAM** | Everything anchored to GPS-derived ENU via `robot_localization` EKF; leader OctoMap canonical; followers project detections *into* the map, not contribute geometry; map_merge on GCS, not in-flight. |
| **SITL → reality drift** | Same firmware binary in SITL and on Pixhawk; the Phase 2.5 demo flies only behind a condensed props-off safety gate, the full HIL matrix runs at Phase 6 before the field mission; Gazebo sensor noise tuned from real flight logs each iteration. |
| **Phase 2.5 demo: WiFi inside the formation loop, flight before full HIL** | Followers track the leader over the Cyclone DDS LAN — a dropout would otherwise leave a follower coasting on a stale setpoint. Phase 2.5a rehearses the whole loop in SITL before any hardware flight; a follower-side leader-pose watchdog (stale → hold / LOITER); generous spacing and low leader speed keep tracking latency non-critical; one safety pilot per drone with RC override; condensed props-off safety gate (calibration + geofence + GUIDED arm test) is a hard prerequisite. Native ArduPilot FOLLOW mode is the documented fallback (ADR 0008). |
| **Dependency supply chain** | Every dep pinned: git SHA in `.repos`, pip hash, apt version, Docker digest; `digests.lock` regenerated quarterly; build scripts fail loudly if anything unpinned. |
| **Operator cognitive load** | the MAVLink GCS (Mission Planner / QGC) owns safety (mode/geofence/arm/RTL); Foxglove owns mission (formation/search/perception); operator runbook specifies which tool for which task; Phase 7 entry requires tabletop dry run. |

---

## H. Verification Plan for the Plan Itself

- `docker buildx build --platform linux/amd64,linux/arm64 -f docker/base.Dockerfile .` — Phase 0 gate.
- `docker compose -f docker/compose.dev.yaml up` — Phase 1 gate; SITL + MAVROS + Foxglove healthy <60 s.
- `bash scripts/ci/run_sitl_smoke.sh` — Phase 1 acceptance; arm, takeoff 5 m, waypoint, land, exit 0.
- `bash scripts/bringup/sitl_swarm.sh` — Phase 2 gate; 5 drones in diamond, <0.5 m drift logged.
- `make swarm-up` + `/swarm/follow_leader` — Phase 2.5a SITL gate; the operator moves the leader in the Gazebo swarm, the four followers track the diamond live <0.5 m.
- `bash scripts/bringup/demo_swarm.sh` — Phase 2.5b hardware gate; manually-piloted leader, ≥2 followers hold a live leader-relative formation <2 m error for ≥60 s; safety-pilot sign-off on `docs/runbooks/first_flight.md`.
- `colcon test --packages-select swarm_control swarm_perception swarm_mapping swarm_behaviors` — unit gate, 70%+ coverage.
- `ros2 launch swarm_bringup sitl_swarm.launch.py world:=search_field` — full sim; in Foxglove send `/swarm/start_search` action with polygon — expect ≥2 of 3 actors detected and converged within 5 min.

---

## I. Critical Files (in order of implementation)

1. `v2/PLAN.md` — this document.
2. `v2/docker/base.Dockerfile` — gates everything; multi-arch ROS 2 Humble.
3. `v2/.github/workflows/sitl_smoke.yml` — fixes v1 mistake #3.
4. `v2/ros2_ws/src/swarm_control/swarm_control/mavros_adapter.py` — v1-to-v2 lynchpin.
5. `v2/ros2_ws/src/swarm_sim/swarm_sim/sitl_launcher.py` — multi-instance SITL launcher; Phase 2 hinge.
6. `v2/ros2_ws/src/swarm_perception/swarm_perception/yolo_detector_node.py` — Phase 3 hinge.
7. `v2/ros2_ws/src/swarm_mapping/launch/leader_lio.launch.py` — Phase 4 hinge.
8. `v2/ros2_ws/src/swarm_behaviors/trees/search_and_rescue.xml` — Phase 5 BT.

---

## J. Out of Scope for v2.0.0

- ML training pipelines (model is pretrained; fine-tuning on aerial SAR datasets is v2.1).
- Drone manipulation (grippers, payload delivery) — hardware lacks it.
- Indoor/GPS-denied operation — mission profile is outdoor SAR.
- AP_DDS native ROS 2 (deferred behind adapter).
- Ego-Planner-v2 (deferred to Phase 6+).
- Multi-leader / dynamic leader election (fixed `drone_0`).
- Encrypted MAVLink links (v2.1 hardening pass).
