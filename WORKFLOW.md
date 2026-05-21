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
| 1 | Single-drone ArduPilot SITL + MAVROS + Foxglove | Ready to start |
| 2 | 5-drone SITL swarm + diamond formation | Not started |
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
   first-party workspace only and does not `vcs import` these.

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

## Current focus

Phase 0 closed. Next: Phase 1 (single-drone SITL).

## Next — Phase 1 entry

Phase 1 (single-drone SITL) starts once Phase 0 is green. First tasks:

- Port `vehicle_adapter.py` + `swarm_api.py` from v1 into `swarm_control/`.
- Implement `mavros_adapter.py` (the v1→v2 lynchpin — see `PLAN.md` § I).
- `sitl_single.launch.py` + verify `compose.dev.yaml` cold-starts in <60 s.
- Re-pin `ardupilot` / `ardupilot_gz` / `ardupilot_gazebo` in `orynth.repos` to
  the refs validated against SITL.

---

## Document changelog

- **2026-05-21** — Created. Phase 0 implementation pass: pins resolved, build
  blockers fixed, unit test added, CI reworked. Phase 0 acceptance gate passed
  locally (amd64); phase marked complete.
