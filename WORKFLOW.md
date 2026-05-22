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
| 2 | 5-drone SITL swarm + diamond formation | Not started |
| 2.5 | Hardware demo: leader-follow swarm | Not started |
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

## Current focus

Phase 1 complete. Next: Phase 2 (5-drone SITL swarm + diamond formation), then
the Phase 2.5 hardware-demo milestone — leader-follow swarm on real airframes.

## Next — Phase 2 entry

Phase 2 (5-drone SITL swarm + diamond formation) — first tasks:

- `swarm_sim/sitl_launcher.py` — multi-instance SITL at offset spawn points,
  per-instance ports (PLAN § I, critical file #5).
- `swarm_server_node` exposing `/swarm/takeoff|land|engage_formation`.
- Port + extend `formation.py` — build it **reference-agnostic** (a static
  centroid now; the Phase 2.5 demo feeds the same code a live leader pose);
  implement `MavrosAdapter.hold_reference`.
- `compose.swarm.yaml` + wire the `sitl-5-drone-swarm` nightly job.

---

## Phase 2.5 — Hardware Demo: Leader-Follow Swarm (planned)

A milestone, not a numbered phase: the first **on-hardware** flight, run after
Phase 2. An operator manually manipulates the leader (`drone_0`); ≥2 followers
autonomously hold a formation relative to the leader's live pose and track it as
it moves. Mapping, computer vision, and autonomous search stay post-demo
(Phases 3-5, unchanged). Specced in `PLAN.md` § D, Phase 2.5; integration
decision in [`docs/adr/0008-leader-follow-demo-integration.md`](docs/adr/0008-leader-follow-demo-integration.md).

**Integration**: followers fly GUIDED, commanded by `swarm_server_node` through
`MavrosAdapter`; the formation reference is the leader's live MAVROS pose — a
small generalization of Phase 2's `formation.py`. Native ArduPilot FOLLOW mode
(`FOLL_SYSID` / `FOLL_OFS_*`) is the documented fallback (ADR 0008).

**Entry criteria** (before any motor spins):

- Phase 2 complete — `formation.py` / `swarm_server_node` proven in 5-drone SITL.
- `formation.py` confirmed reference-agnostic — the demo feeds it a live leader
  pose with no rewrite.
- Condensed safety gate (a subset of the Phase 6 HIL checklist): per-airframe
  compass/accel calibration, props-off GUIDED arm test, geofence + RC-loss
  failsafe via QGC, single-drone manual hover for the leader and each follower.

**First tasks**:

- Leader-relative formation mode in `swarm_control` — `formation.py` live
  reference, `MavrosAdapter.hold_reference` moving-setpoint tracking,
  `/swarm/follow_leader` engage/disengage, follower-side leader-pose watchdog.
- `scripts/bringup/demo_swarm.sh` + per-airframe params in
  `config/ardupilot_params/`.
- `docs/runbooks/first_flight.md` demo runbook; `demo.json` Foxglove layout.

**Acceptance gate** (`PLAN.md` § D): manually-piloted leader, ≥2 followers
(target 4) tracking a live leader-relative formation <2 m mean horizontal error
for ≥60 s of leader motion; watchdog holds a follower on a simulated link drop;
coordinated land. Recorded `accept/demo_leaderfollow.mcap` + flight video;
safety-pilot + maintainer sign-off — no CI gate (hardware).

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
