# Orynth v2 — Workflow & Status

> **Living document.** `PLAN.md` is the contract (what & why); `WORKFLOW.md` is
> the status board (where we are). Update this on every phase transition, every
> notable decision, and whenever a deviation from `PLAN.md` is taken.
>
> Last updated: **2026-05-21**

---

## Phase status

| Phase | Title | Status |
|---|---|---|
| 0 | Repo scaffold + CI + Docker baseline | **Complete** — 2026-05-21 |
| 1 | Single-drone ArduPilot SITL + MAVROS + Foxglove | **Complete** — 2026-05-21 |
| 2 | 5-drone SITL swarm + diamond formation | **Complete** — 2026-05-21 |
| 2.5a | Leader-follow SITL rehearsal | **Complete** — 2026-05-21 |
| 2.5b | Hardware demo: leader-follow swarm | Artifacts complete — awaiting hardware flight |
| 3 | YOLO human detection + Isaac ROS pipeline | Not started |
| 4 | LiDAR mapping (FAST-LIO2 + OctoMap) | Not started |
| 5 | Autonomous search + Nav2 | Not started |
| 6 | Hardware-in-the-loop | Not started |
| 7 | Full 5-drone field deployment | Not started |

---

## Phase 0 — checklist

Deliverables per `PLAN.md` § D, Phase 0.

- [x] Full directory tree (`docker/`, `ros2_ws/src/` × 10 packages, `config/`,
      `scripts/`, `docs/`, `.github/workflows/`)
- [x] Multi-arch `base.Dockerfile` — amd64 (`ros:humble-ros-base-jammy`) +
      arm64 (`nvcr l4t-jetpack:r36.3.0`), both pinned by SHA256 digest
- [x] ADRs 0001–0007 drafted (`docs/adr/`)
- [x] `swarm_perception` ships a working passthrough detector node
- [x] Pre-commit hooks (`.pre-commit-config.yaml`)
- [x] `orynth.repos` — every external git dep pinned by real SHA (no sentinels)
- [x] `docker/digests.lock` + `docker/requirements.txt` — real digests / hashes
- [x] `swarm_perception` unit test (passthrough contract)
- [x] `LICENSE`, `.dockerignore`, `scripts/build/refresh_pins.sh`
- [x] `lint.yml` green — verified locally via `pre-commit run --all-files`
- [x] `unit.yml` green — `colcon build && colcon test` inside the base image
- [x] Acceptance: `docker buildx build` succeeds; fresh-clone-to-dev <10 min

### Phase 0 fixes applied (this pass)

The scaffold from commit `b28f9f3` was structurally complete but would not
build. Corrections:

| Problem | Fix |
|---|---|
| `base.Dockerfile` / `digests.lock` had all-zero placeholder digests | Pinned real SHA256 digests (resolved 2026-05-21) |
| `requirements.txt` had all-zero pip hashes; `ultralytics` would drag Torch into the base image | Trimmed to Phase 0–2 pure-Python deps (`pexpect`, `ptyprocess`) with real hashes |
| `orynth.repos` had all-zero git SHAs (`build_workspace.sh` sentinel would reject every build) | Resolved real SHAs for all 9 external repos |
| `base.Dockerfile` never installed `colcon` on the amd64 path (the ROS bootstrap block only runs on the Jetson base) | Moved `colcon`/`rosdep`/`vcstool`/`pip` into the unconditional apt layer |
| `base.Dockerfile` `COPY requirements.txt` — wrong path; build context is the repo root | `COPY docker/requirements.txt` |
| `swarm_behaviors/CMakeLists.txt` had `find_package(behaviortree_cpp REQUIRED)` with zero C++ sources | Reduced to a minimal scaffold CMakeLists (deps return in Phase 5) |
| `setup.py` entry points referenced node modules that do not exist yet (`swarm_server`, `bandwidth_manager`, `sitl_launcher`, `detection_geolocator`, …) | Removed dangling console scripts; kept `yolo_detector` |
| `unit.yml` built against a plain ROS base + `rosdep --skip-keys` (drifts from the real dep set) | Rewritten to build + test inside the `orynth-base` image |
| Maintainer email was the old GitHub account (`nikolamarkovic.idea@gmail.com`) | Updated all `package.xml` + `setup.py` to `dev.markovic@protonmail.com` |

---

## How to verify Phase 0

```bash
# 1. Lint gate
pip install pre-commit==3.7.1
pre-commit run --all-files

# 2. Build the base image (amd64)
docker buildx build --load -f docker/base.Dockerfile -t orynth-base:dev .

# 3. Unit gate — build + test the workspace inside the base image
docker run --rm -v "$PWD":/workspace -w /workspace/ros2_ws orynth-base:dev \
  bash -c 'colcon build --packages-skip swarm_hardware &&
           colcon test --packages-skip swarm_hardware --return-code-on-test-failure &&
           colcon test-result --verbose'

# 4. Pin audit
bash scripts/build/refresh_pins.sh
```

CI runs the same gates: `lint.yml` (pre-commit + dockerfile-pin-check),
`unit.yml` (colcon build/test in the base image), `docker_build.yml`
(multi-arch amd64+arm64 on `main`).

---

## Known deviations from PLAN.md

Recorded so the team can ratify or reverse them.

1. **apt packages are not version-pinned** in `base.Dockerfile`. ADR 0007 asks
   for `pkg=version`. Pinning ~20 ROS apt packages to exact versions is fragile
   — the ROS apt repo drops old versions, so a pinned build breaks within
   weeks. Non-fragile apt pinning needs a ROS **snapshot mirror**
   (`snapshots.ros.org`-style). **Decision needed**: adopt a snapshot mirror, or
   accept apt as the one unpinned layer. Docker digest + git SHA + pip hash
   pinning are all in place.

2. **`requirements.txt` trimmed to Phase 0–2 scope.** `ultralytics` (and its
   Torch / CUDA closure) is *not* in the base image — it is ~3 GB and unused
   until Phase 3. It will be added in a dedicated Phase 3 `requirements.txt`
   bump, pinned with the full transitive hash set. `numpy`/`opencv` come from
   apt (`python3-opencv` via `cv_bridge`).

3. **Multi-arch acceptance — arm64 leg validated in CI, not locally.** The
   `base.Dockerfile` is correct for both arches and `docker_build.yml` builds
   `linux/amd64,linux/arm64` on `main`. Local Phase 0 verification builds amd64
   only: the arm64 leg cross-builds a ~9 GB Jetson base under QEMU emulation,
   which is impractical on a dev workstation.

4. **`orynth.repos` SHAs are forward pins.** Most external repos are not
   imported until the phase that needs them. SHAs were pinned to upstream HEAD
   on 2026-05-21 (except `ardupilot`, pinned to tag `Copter-4.5.7`). Re-pin to
   the phase's validated ref when each phase begins. Phase 0 builds the
   first-party workspace only and does not `vcs import` these. Phase 1
   validated `ardupilot` @ `Copter-4.5.7` against SITL; `ardupilot_gazebo` @ its
   pinned SHA now builds cleanly in the SITL image but is not exercised until
   Phase 2 runs Gazebo; `ardupilot_gz` stays a forward pin.

5. **`compose.dev.yaml` companion builds its overlay at container start.** The
   `companion` service `colcon build`s `swarm_control` + `swarm_bringup` into
   `/opt/overlay` on `up`, rather than baking them into an image. This keeps the
   edit→`up` dev loop rebuild-free; it adds ~15–25 s to cold-start, so the <60 s
   PLAN § D gate is measured with the base/SITL images already built.

6. **`PlatformProfile` trimmed.** `PLAN.md` § F asks to add
   `ARDUPILOT_HARDWARE`; v1's `AEROSTACK2_SIM` is also dropped — v2 is
   MAVROS-only (ADR 0002). The enum is now `ARDUPILOT_SITL` +
   `ARDUPILOT_HARDWARE`.

7. **The Phase 2 acceptance gate runs pure-SITL, not Gazebo.** Deviation 4
   anticipated Phase 2 "runs Gazebo". The headless acceptance gate
   (`sitl_swarm.sh` / the nightly CI job) runs ArduPilot's built-in `quad`
   physics: all SITL share one home so every drone's local frame coincides
   (frame-clean formation math), it is fast, and it needs no GPU/X. Gazebo
   Harmonic is wired as the *on-screen* backend — `docker/compose.swarm.gui.yaml`
   / `make swarm-up` — running the identical `swarm_server` / formation stack
   with distinct-home SITL and GPS-calibrated field offsets. Both are Phase 2
   deliverables; the gate simply does not depend on Gazebo rendering.

---

## Phase 0 acceptance results (2026-05-21)

Verified locally on an amd64 workstation (Docker 24 + buildx 0.34):

| Gate | Result |
|---|---|
| `docker buildx build base.Dockerfile` (amd64) | Pass — `orynth-base:dev`, 3.76 GB |
| `colcon build --packages-skip swarm_hardware` | Pass — 9 packages, 5.7 s |
| `colcon test` | Pass — 3 tests, 0 errors, 0 failures |
| `pre-commit run --all-files` | Pass — all hooks |
| dockerfile-pin-check (no unpinned `FROM`) | Pass |
| `scripts/build/refresh_pins.sh` | Pass — all pins resolvable |

arm64 leg not built locally (see deviation 3); `docker_build.yml` covers it on
`main`.

## Phase 1 — checklist

Deliverables per `PLAN.md` § D, Phase 1.

- [x] `swarm_control/swarm_api.py` + `vehicle_adapter.py` — ported from v1
- [x] `swarm_control/mavros_adapter.py` — `MavrosAdapter` implementing the
      `VehicleAdapter` contract against MAVROS (PLAN § I, critical file #4)
- [x] `swarm_control/sitl_mission.py` — Phase 1 acceptance mission, exposed as
      the `sitl_mission` console script
- [x] `swarm_bringup/launch/sitl_single.launch.py` — MAVROS + Foxglove bringup
- [x] `compose.dev.yaml` — `sitl` + `companion` services, both healthchecked
- [x] `scripts/ci/run_sitl_smoke.sh` — drives the mission through the adapter
      (replaces the Phase 0 placeholder `ros2 service call` script)
- [x] `swarm_control` unit tests — adapter + API tests against a fake MAVROS
      node, no live SITL (`colcon test` green: 22 tests, 0 failures)
- [x] `sitl_smoke.yml` — single-drone PR gate, GitHub Actions layer cache
- [x] `Makefile` — wraps Phase 0/1 commands; `make shell` for an interactive
      container
- [x] Acceptance gate — full SITL mission passed; see "Phase 1 acceptance
      results" below

### Phase 1 fixes applied (this pass)

| Problem | Fix |
|---|---|
| `sitl.Dockerfile` ran ArduPilot's `install-prereqs-ubuntu.sh` as root, which the script refuses (`exit 1`) | Build ArduPilot as a non-root `apbuild` user with passwordless sudo |
| `sitl.Dockerfile` declared an unused `ARDUPILOT_GZ_REF` and cloned `ardupilot_gazebo` at the moving `main` ref | Removed the unused ARG; pinned `ARDUPILOT_GAZEBO_REF` to the `orynth.repos` SHA (ADR 0007) |
| `compose.dev.yaml` had no healthchecks, so `--wait` and the <60 s gate could not be enforced | Added TCP / `/mavros/state` healthchecks to both services |
| `sitl_smoke.yml` built `:ci`-tagged images that `compose.dev.yaml` (which expects `:dev`) never used | Aligned tags to `:dev`; added a GHA buildx layer cache |

### Phase 1 fixes applied (acceptance pass)

Found while running the acceptance gate end to end:

| Problem | Fix |
|---|---|
| `sitl.Dockerfile` never installed the GStreamer/RapidJSON/OpenCV dev packages `ardupilot_gazebo`'s CMake requires (`pkg_check_modules REQUIRED gstreamer-app-1.0`) — the SITL image build failed | Added the documented `ardupilot_gazebo` prerequisites in a layer *after* the slow (cached) ArduPilot build |
| `sitl_companion.sh` ran under `set -u`; colcon's generated `setup.bash` dereferences unset vars (`COLCON_TRACE`) → companion exited 1, `up --wait` aborted | Bracket the overlay `source` with `set +u` / `set -u` |
| Running the `arducopter` binary directly leaves `FRAME_CLASS=0` → `PreArm: Motors: Check frame class and type`, vehicle never armed | Load ArduPilot's `copter.parm` SITL defaults via `arducopter --defaults` |
| MAVROS (ROS 2) does not request MAVLink data streams and `arducopter` streams nothing by default → `/mavros/local_position/pose` silent, every takeoff/waypoint altitude check timed out | Added `docker/sitl-params.parm` (serial0 `SR0_*` stream rates), layered via `--defaults` |

## How to verify Phase 1

```bash
# Unit gate — adapter contract, no SITL
make test

# Acceptance — full single-drone SITL mission (builds images on first run)
make sitl-smoke

# Acceptance + recording
make sitl-accept    # also writes accept/phase1.mcap
```

CI runs the same: `unit.yml` (colcon test) and `sitl_smoke.yml` (single-drone
SITL smoke on every PR).

## Phase 1 acceptance results (2026-05-21)

Verified locally on an amd64 workstation via `make test` + `make sitl-accept`:

| Gate | Result |
|---|---|
| `colcon build && colcon test` (unit gate) | Pass — 22 tests, 0 errors, 0 failures |
| `docker buildx build` `orynth-sitl:dev` (ArduPilot SITL + Gazebo) | Pass |
| `docker compose up --wait` cold-start | Pass — stack healthy in 7 s (gate: <60 s) |
| GUIDED → arm | Pass — armed ~37 s after start (GPS/EKF convergence) |
| Takeoff to 5 m | Pass — altitude reached ~6 s after command |
| Waypoint to (10, 0, 5) | Pass — reached ~4 s after command |
| Land + disarm | Pass — disarmed ~13 s after command |
| Acceptance bag | Pass — `accept/phase1.mcap` recorded (`/mavros/state`, `local_position/pose`, `setpoint_raw/local`) |

## Phase 2 — checklist

Deliverables per `PLAN.md` § D, Phase 2.

- [x] `swarm_sim/sitl_launcher.py` — multi-instance ArduPilot SITL launcher
      (ports `5760+N*10`, per-instance `SYSID_THISMAV`, pure-SITL or Gazebo)
- [x] `swarm_sim/world_builder.py` — generates the N-drone Gazebo Harmonic
      world from `iris_with_ardupilot` (per-model FDM ports)
- [x] `swarm_control/formation.py` — reference-agnostic formation geometry
      (diamond / vee / column / line)
- [x] `MavrosAdapter.hold_reference` — formation-hold setpoint streaming;
      `global_position` for the GPS-calibrated common field frame
- [x] `swarm_control/swarm_server_node.py` — 5-drone orchestrator: services
      `/swarm/takeoff|land|engage_formation`, `/swarm/drone_<N>/manual_goto`,
      formation control loop, `SwarmStatus` publisher
- [x] `swarm_msgs` — `SwarmTakeoff` + `ManualGoto` service definitions
- [x] `swarm_bringup/launch/sitl_swarm.launch.py` — 5× MAVROS + Foxglove +
      swarm_server
- [x] `docker/compose.swarm.yaml` (+ `compose.swarm.gui.yaml` GUI overlay) and
      the `swarm_sim` / `swarm_companion` bringup scripts
- [x] `scripts/bringup/sitl_swarm.sh` — Phase 2 acceptance gate runner
- [x] `swarm_bringup/config/operator.json` — Foxglove layout showing all 5
- [x] unit tests — formation geometry + `swarm_server` (5-fake-MAVROS
      integration) + `swarm_sim` (`colcon test` green: 48 tests, 0 failures)
- [x] `Makefile` `swarm-smoke` / `swarm-up` / `swarm-down`; `sitl_smoke.yml`
      nightly `sitl-5-drone-swarm` job wired to `sitl_swarm.sh`
- [x] Acceptance gate — 5-drone takeoff, diamond hold, land; see "Phase 2
      acceptance results" below

### Phase 2 fixes applied (acceptance pass)

Found while running the acceptance gate end to end:

| Problem | Fix |
|---|---|
| `sitl_launcher.main()` read the module-global `_stop` before assigning it → `UnboundLocalError` | Declared `global _stop` in `main()` |
| `swarm_sim.sh` `cd`'d to `ros2_ws/src`, so `python -m swarm_sim.*` resolved a stale colcon `install/` tree | `cd` to the package root `src/swarm_sim` (cwd = `sys.path[0]`) |
| Companion overlay built with `--packages-select`; an ament_cmake package's `exec_depend`s must be built, so `swarm_bringup` failed its colcon cmake check | Build the dependency closure with `--packages-up-to swarm_bringup` |
| All five MAVROS shared MAVLink system id 1 → a shared `/uas1` router prefix → a node-name collision silently killed one MAVROS | Per-instance `SYSID_THISMAV = N+1` (`sitl_launcher`) + matching `tgt_system` (`sitl_swarm.launch.py`) — PLAN § G's SYSID mitigation |

## How to verify Phase 2

```bash
# Unit gate — formation, swarm_server, swarm_sim; no SITL
make test

# Acceptance — headless 5-drone SITL swarm (builds images on first run)
make swarm-smoke

# On-screen — 5 drones in Gazebo Harmonic, GUI on the host display
make swarm-up      # then connect Foxglove to ws://localhost:8765
make swarm-down
```

CI runs `unit.yml` (`colcon test`) on every PR and `sitl_smoke.yml`
(`sitl-5-drone-swarm`) nightly.

## Phase 2 acceptance results (2026-05-21)

Verified locally on an amd64 workstation via `make test` + `make swarm-smoke`:

| Gate | Result |
|---|---|
| `colcon build && colcon test` (unit gate) | Pass — 48 tests, 0 errors, 0 failures |
| `docker compose up --wait` cold-start (5 SITL + 5 MAVROS + server) | Pass — stack healthy in 12 s (gate: <60 s) |
| `/swarm/takeoff` — coordinated 5-drone takeoff to 5 m | Pass — all 5 armed + airborne |
| `/swarm/engage_formation` diamond, spacing 4 m | Pass — diamond latched |
| Diamond formation hold, 60 s | Pass — **0.02 m mean drift** per follower (gate: <0.5 m) |
| `/swarm/land` — coordinated land + disarm | Pass — all 5 landed |

Gazebo Harmonic is the on-screen backend (`make swarm-up`); the gate itself
runs frame-clean pure-SITL (deviation 7).

## Current focus

Phases 0–2 and **Phase 2.5a** complete; **Phase 2.5b** artifacts ready, awaiting
the hardware flight. Next: run the 2.5b first-flight
(`docs/runbooks/first_flight.md`) on real airframes, then Phase 3 (YOLO human
detection).

---

## Phase 2.5 — Leader-Follow Demo

A milestone in two stages: an operator manipulates the leader (`drone_0`) and
the followers autonomously hold a diamond relative to the leader's *live* pose,
tracking it as it moves. **2.5a** proves this in the SITL swarm; **2.5b** flies
it on real airframes — so no airframe flies a behaviour the simulator has not
already shown. Mapping, computer vision, and autonomous search stay post-demo
(Phases 3-5, unchanged). Specced in `PLAN.md` § D, Phase 2.5; integration
decision in [`docs/adr/0008-leader-follow-demo-integration.md`](docs/adr/0008-leader-follow-demo-integration.md).

**Integration** (both stages): followers fly GUIDED, commanded by
`swarm_server_node` through `MavrosAdapter`; the formation reference is the
leader's live MAVROS pose — a small generalization of Phase 2's `formation.py`.
Native ArduPilot FOLLOW mode (`FOLL_SYSID` / `FOLL_OFS_*`) is the documented
fallback (ADR 0008).

### Phase 2.5a — checklist

Deliverables per `PLAN.md` § D, Phase 2.5a.

- [x] `swarm_msgs/FollowLeader.srv` — engage/disengage service definition
- [x] `MavrosAdapter` — `pose_age_s` (live-pose staleness) + `heading_rad`
      (ENU yaw from the pose quaternion) for the follow loop and its watchdog
- [x] `swarm_server_node` — `/swarm/follow_leader` live-reference control loop:
      the formation re-places around `drone_0`'s *live* pose every tick (slot 0
      never commanded — the operator flies the leader)
- [x] Follower-side leader-pose watchdog — a stale leader pose freezes the
      followers on the last good reference (hold position) and raises the
      `/swarm/status` emergency; `simulate_leader_dropout` param exercises it
- [x] `/swarm/formation_error` — per-drone horizontal error topic for `demo.json`
- [x] `scripts/bringup/leaderfollow_sitl.sh` — Phase 2.5a acceptance gate;
      `Makefile` `leaderfollow-smoke`; nightly `sitl_smoke.yml` step
- [x] Integration tests — leader-follow tracking, watchdog hold/recover,
      formation-error topic, adapter pose-age/heading (`colcon test` green:
      55 tests, 0 failures)
- [x] Acceptance gate passed — see "Phase 2.5a acceptance results" below

### Phase 2.5a acceptance results (2026-05-21)

Verified locally on an amd64 workstation via `make test` + `make
leaderfollow-smoke`:

| Gate | Result |
|---|---|
| `colcon build && colcon test` (unit gate) | Pass — 55 tests, 0 errors, 0 failures |
| `docker compose up --wait` cold-start (5 SITL + 5 MAVROS + server) | Pass — stack healthy in 13 s |
| `/swarm/takeoff` — coordinated 5-drone takeoff to 5 m | Pass — all 5 airborne |
| `/swarm/follow_leader` engage (diamond, 4 m) | Pass — 4 followers shadowing |
| Operator flies the leader (2 legs via `manual_goto`); followers track | Pass — **0.05 m worst settled drift** (gate: <0.5 m) |
| Leader-pose watchdog on a simulated dropout | Pass — followers held position |
| `/swarm/follow_leader` disengage + `/swarm/land` | Pass — all 5 landed |

The gate runs headless pure-SITL (consistent with deviation 7); `make swarm-up`
gives the on-screen Gazebo version of the same demo.

### Phase 2.5b — checklist

Deliverables per `PLAN.md` § D, Phase 2.5b.

- [x] `docker/compose.demo.yaml` — per-Jetson hardware bringup, `DRONE_ID`-
      namespaced, host networking for the cross-Jetson DDS LAN
- [x] `swarm_bringup/launch/hw_drone.launch.py` + `scripts/bringup/demo_companion.sh`
      — namespaced single-drone hardware bringup; the leader's Jetson also hosts
      the Foxglove bridge + `swarm_server`
- [x] `scripts/bringup/demo_swarm.sh` — operator bringup wrapper + swarm-wide
      preflight gate (blocks until every drone reports a live FC link, EKF
      global origin, and battery > 90%)
- [x] `config/ardupilot_params/` — per-airframe demo params (geofence, RC/GCS/
      battery failsafes, GUIDED tuning, distinct `SYSID_THISMAV`) + README
- [x] `docs/runbooks/first_flight.md` — demo flight runbook (condensed safety
      gate, roles, sequence, abort triggers, sign-off)
- [x] `swarm_bringup/config/demo.json` — Foxglove demo layout (poses,
      `/swarm/status`, live per-follower formation error)
- [x] `docs/runbooks/jetson_swarm_operations.md` — Jetson setup + single-drone /
      swarm control guide
- [x] `Makefile` `demo-up` / `demo-check` / `demo-down`
- [ ] **Acceptance — the hardware flight.** Pending real airframes: manually-
      piloted leader, ≥2 followers (target 4) tracking a live leader-relative
      formation <2 m mean error for ≥60 s of leader motion; watchdog holds a
      follower on a simulated link drop; coordinated land. Recorded
      `accept/demo_leaderfollow.mcap` + flight video; safety-pilot + maintainer
      sign-off on `first_flight.md` — no CI gate (hardware).

Entry criteria before any motor spins: Phase 2.5a passed in SITL (done) + the
condensed safety gate in `first_flight.md` § 2 (per-airframe calibration,
props-off GUIDED arm test, geofence + RC-loss failsafe via QGC, single-drone
manual hover for the leader and each follower).

---

## Document changelog

- **2026-05-21** — Created. Phase 0 implementation pass: pins resolved, build
  blockers fixed, unit test added, CI reworked. Phase 0 acceptance gate passed
  locally (amd64); phase marked complete.
- **2026-05-21** — Phase 1 implementation pass: `MavrosAdapter` + `swarm_api` /
  `vehicle_adapter` ported, `sitl_mission` runner, `sitl_single.launch.py`,
  healthchecked `compose.dev.yaml`, adapter-driven smoke test, `Makefile`,
  unit tests. `sitl.Dockerfile` non-root build fix.
- **2026-05-21** — Phase 1 acceptance pass: ran the gate end to end. Four
  blockers fixed (`ardupilot_gazebo` GStreamer deps, `sitl_companion.sh`
  `set -u`, SITL `FRAME_CLASS`, MAVLink stream rates — see "Phase 1 fixes
  applied (acceptance pass)"). Full SITL mission (arm/takeoff/waypoint/land)
  passes; `accept/phase1.mcap` recorded. Phase 1 marked complete.
- **2026-05-21** — Added the **Phase 2.5 hardware-demo milestone**
  (leader-follow swarm) to the roadmap: `PLAN.md` § D (new phase) plus § B/§ E/
  § G/§ H, new ADR 0008 (ROS-side leader-relative formation over native FOLLOW
  mode), status table, and the planned-section above. A deliberately minimal
  first-on-hardware-flight checkpoint after Phase 2 — manual leader manipulation
  + followers in formation; mapping/CV remain Phases 3-5.
- **2026-05-21** — Phase 2 implementation pass: 5-drone SITL swarm.
  `formation.py` (diamond/vee/column/line), `MavrosAdapter.hold_reference`,
  `swarm_server_node` (takeoff/land/engage_formation/manual_goto + SwarmStatus),
  `sitl_launcher.py` + `world_builder.py`, `sitl_swarm.launch.py`,
  `compose.swarm.yaml` (+ GUI overlay), `operator.json`. Acceptance gate passed:
  5-drone coordinated takeoff, diamond hold at 0.02 m mean drift (gate <0.5 m),
  coordinated land; 48 unit tests green. Four blockers fixed (see "Phase 2 fixes
  applied"). Deviation 7 added (pure-SITL gate, Gazebo on-screen). Phase 2
  marked complete.
- **2026-05-21** — Split the Phase 2.5 milestone into two stages: **2.5a**
  Leader-Follow SITL Rehearsal (the operator moves the leader in the Gazebo
  swarm, followers track the diamond live — proven before any hardware) and
  **2.5b** Hardware Demo (the on-airframe flight). `PLAN.md` § D / § E / § G /
  § H and this section restructured; status table now lists 2.5a + 2.5b. The
  leader-follow code (`/swarm/follow_leader` live-reference mode + watchdog)
  moves from a hardware-only task to the SITL-first 2.5a stage.
- **2026-05-21** — Phase 2.5a implementation pass: leader-follow in the SITL
  swarm. `FollowLeader.srv`, `MavrosAdapter` live-pose age + heading,
  `swarm_server_node` `/swarm/follow_leader` live-reference loop + leader-pose
  watchdog + `/swarm/formation_error`, `leaderfollow_sitl.sh` gate + CI step.
  Acceptance gate passed: 5-drone takeoff, operator-flown leader, 4 followers
  tracking at 0.05 m worst settled drift (gate <0.5 m), watchdog hold on a
  simulated dropout; 55 unit tests green. Phase 2.5a marked complete.
- **2026-05-21** — Phase 2.5b artifacts pass: the hardware leader-follow demo.
  `compose.demo.yaml` (per-Jetson, `DRONE_ID`-namespaced, host networking),
  `hw_drone.launch.py` + `demo_companion.sh`, `demo_swarm.sh` (bringup +
  preflight health gate), `config/ardupilot_params/` per-airframe demo params,
  `demo.json` Foxglove layout, `docs/runbooks/first_flight.md` (flight runbook)
  and `docs/runbooks/jetson_swarm_operations.md` (Jetson setup + control guide).
  All artifacts complete and validated; the 2.5b acceptance is the hardware
  flight itself, pending real airframes.
