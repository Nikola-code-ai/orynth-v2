# Orynth v2 — Command Reference

> Step-by-step commands to reproduce and verify each phase. Companion to
> `PLAN.md` (what & why) and `WORKFLOW.md` (status).
>
> **Conventions**
> - All commands run from the repo root (`v2/`) unless stated otherwise.
> - `$` denotes a host shell; commands inside a container are noted as such.
> - No local ROS 2 install is required — the workspace builds and tests
>   *inside* the `orynth-base` Docker image.
> - **No step drops you into an interactive container.** Every container step
>   is an ephemeral `docker run --rm` or a `docker compose` service that runs
>   one command and exits. `make shell` is the only interactive entry point.
> - `make` wraps the common Phase 0/1 commands — run `make help` for the list.

---

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Docker Engine | 24+ | base image build, containerised colcon |
| Docker buildx | 0.12+ | multi-arch build, digest resolution |
| git | 2.30+ | clone, pin resolution (`git ls-remote`) |
| Python 3 | 3.10+ | `pre-commit` (in a venv — see step 0.4) |

Verify:

```bash
$ docker --version
$ docker buildx version
$ git --version
$ python3 --version
```

---

## Phase 0 — Repo scaffold + CI + Docker baseline

Phase 0 produces a reproducible build/test/lint baseline. Reproduce it in six
steps. Total time on a fresh clone: well under 10 minutes (the base image
build dominates, ~3–6 min on a warm Docker cache).

### 0.1 — Clone

```bash
$ git clone https://github.com/Nikola-code-ai/orynth-v2.git
$ cd orynth-v2
```

### 0.2 — Build the base image (amd64)

The base image is ROS 2 Humble + MAVROS + Cyclone DDS + the common tooling,
pinned by SHA256 digest (ADR 0007).

```bash
$ docker buildx build --load -f docker/base.Dockerfile -t orynth-base:dev .
```

Expected: image `orynth-base:dev` (~3.8 GB), exit 0.

> **Multi-arch:** CI (`docker_build.yml`) builds `linux/amd64,linux/arm64`. The
> arm64 leg cross-builds a ~9 GB Jetson base under QEMU and is impractical
> locally — build amd64 only on a workstation. To attempt both anyway:
> ```bash
> $ docker buildx build --platform linux/amd64,linux/arm64 \
>     -f docker/base.Dockerfile -t orynth-base:multi .
> ```

### 0.3 — Build + test the ROS 2 workspace

`colcon` runs inside the base image; the repo is bind-mounted at `/workspace`.

```bash
$ docker run --rm -v "$PWD":/workspace -w /workspace/ros2_ws orynth-base:dev \
    bash -c '
      set -e
      colcon build --packages-skip swarm_hardware
      colcon test  --packages-skip swarm_hardware --return-code-on-test-failure
      colcon test-result --verbose
    '
```

Expected: `9 packages finished` for build; `22 tests, 0 errors, 0 failures` for
test. (`swarm_hardware` is arm64-only and skipped on amd64.) The suite is
cumulative — 3 tests at Phase 0, 22 once the Phase 1 `swarm_control` adapter
tests land.

### 0.4 — Lint gate

`pre-commit` covers whitespace/EOF/YAML hooks, `ruff`, and `ruff-format`.
Ubuntu's system Python is PEP 668 "externally managed", so install into a venv:

```bash
$ python3 -m venv /tmp/pc-venv
$ /tmp/pc-venv/bin/pip install pre-commit==3.7.1
$ /tmp/pc-venv/bin/pre-commit run --all-files
```

Expected: every hook `Passed` (or `Skipped` for clang-format — no C++ yet).

The lint workflow also rejects unpinned Docker base images. Reproduce that
check:

```bash
$ grep -rE "^FROM [^@$]+:[^@]+\s*$" docker/ && echo "UNPINNED FROM" || echo "OK"
```

### 0.5 — Pin audit

Confirm every digest / git SHA / pip hash is resolved and not drifted:

```bash
$ bash scripts/build/refresh_pins.sh
```

Expected: `RESULT: all pins resolvable; digests.lock matches upstream.`
(`ardupilot` reports `AHEAD` — it is intentionally pinned to tag
`Copter-4.5.7`, behind upstream HEAD.)

### 0.6 — Clean up build artefacts

`colcon` writes `build/ install/ log/` into the bind-mounted workspace as root.
Remove them via the container (avoids host `sudo`):

```bash
$ docker run --rm -v "$PWD":/workspace orynth-base:dev \
    bash -c 'rm -rf /workspace/ros2_ws/build /workspace/ros2_ws/install /workspace/ros2_ws/log'
```

### 0.7 — What CI runs

Pushing to a branch / opening a PR triggers three workflows:

| Workflow | Reproduces locally as |
|---|---|
| `lint.yml` | step 0.4 (pre-commit + dockerfile-pin-check) |
| `unit.yml` | steps 0.2 + 0.3 (base image build, then colcon build/test inside it) |
| `docker_build.yml` | step 0.2 multi-arch (on `main` / docker path changes only) |

Inspect runs:

```bash
$ gh run list --limit 5
$ gh run view <run-id>            # summary
$ gh run view <run-id> --log-failed   # logs of failed steps
```

---

## Phase 1 — Single-drone SITL + MAVROS + Foxglove

Phase 1 brings up one ArduPilot SITL drone and flies an acceptance mission
through the backend-neutral `MavrosAdapter` (PLAN § D / § I). As in Phase 0,
nothing runs in an interactive container — `docker compose` services and
ephemeral `docker run` only.

> **Shortcut:** every step has a `make` target. `make sitl-smoke` runs
> 1.1–1.3 end to end; `make sitl-accept` adds 1.5.

### 1.1 — Build the images

`base.Dockerfile` is the Phase 0 baseline. `sitl.Dockerfile` compiles ArduPilot
Copter at the pinned tag (`Copter-4.5.7`) plus Gazebo Harmonic — the first build
is slow (~20–35 min, ArduPilot from source); later builds hit the layer cache.

```bash
$ docker buildx build --load -f docker/base.Dockerfile -t orynth-base:dev .
$ docker buildx build --load -f docker/sitl.Dockerfile \
    --build-arg BASE_TAG=orynth-base:dev -t orynth-sitl:dev .
```

`run_sitl_smoke.sh` (step 1.3) builds both on demand, so this step is optional.

### 1.2 — Cold-start the dev stack

```bash
$ docker compose -f docker/compose.dev.yaml up -d --wait --wait-timeout 300
```

Two services come up — `sitl` (arducopter) and `companion` (MAVROS + Foxglove
bridge via `sitl_single.launch.py`). `--wait` blocks on both healthchecks; the
PLAN § D gate is a healthy stack in <60 s once images are built. Equivalent:
`make sitl-up`.

### 1.3 — Run the acceptance smoke test

```bash
$ bash scripts/ci/run_sitl_smoke.sh        # or: make sitl-smoke
```

Builds images if needed, cold-starts the stack, then drives
`swarm_control.sitl_mission` inside the `companion` container:
GUIDED → arm → takeoff 5 m → waypoint (10, 0, 5) → land. Exit 0 = pass; the
stack is torn down on exit.

### 1.4 — Unit gate (adapter contract)

The `MavrosAdapter` contract is covered by `colcon test` with no SITL — the
tests run it against an in-process fake MAVROS node.

```bash
$ make test     # colcon build + test inside orynth-base
```

### 1.5 — Record the acceptance bag

```bash
$ SMOKE_RECORD=1 bash scripts/ci/run_sitl_smoke.sh   # or: make sitl-accept
```

Writes `accept/phase1.mcap` (gitignored — archive externally) covering
`/mavros/state`, `/mavros/local_position/pose`, `/mavros/setpoint_raw/local`.

### 1.6 — Foxglove + teardown

With the stack up (1.2), connect Foxglove Studio to `ws://localhost:8765` —
`/mavros/local_position/pose` shows live pose, `/mavros/state` shows arm/mode.
Tear down with:

```bash
$ docker compose -f docker/compose.dev.yaml down -v --remove-orphans  # make sitl-down
```

### 1.7 — What CI runs

| Workflow | Reproduces locally as |
|---|---|
| `sitl_smoke.yml` (`sitl-single-drone`) | steps 1.1–1.3 (`make sitl-smoke`) |
| `unit.yml` | step 1.4 (`make test`) |

`sitl_smoke.yml` runs on every PR; image builds use a GitHub Actions layer
cache, so steady-state runs hit the <8 min smoke-test budget.

---

## Phase 2 — 5-Drone SITL Swarm + Diamond Formation

Phase 2 brings up five ArduPilot SITL drones and flies a diamond-formation
acceptance mission through `swarm_server_node` (PLAN § D / § I #5). As before,
nothing runs in an interactive container.

The swarm has two simulation backends, selected by the compose stack — both run
the *same* `swarm_server` / formation / MAVROS layer:

- **pure-SITL** (`arducopter --model=quad`) — headless, frame-clean, fast; what
  the acceptance gate and CI run.
- **Gazebo Harmonic** — the 3D world (ADR 0003), used for the on-screen review.

> **Shortcut:** `make swarm-smoke` runs the acceptance gate; `make swarm-up`
> brings the swarm up with the Gazebo GUI; `make swarm-down` tears it down.

### 2.1 — Build the images

Phase 2 reuses the Phase 1 images (`orynth-base:dev`, `orynth-sitl:dev`):

```bash
$ docker buildx build --load -f docker/base.Dockerfile -t orynth-base:dev .
$ docker buildx build --load -f docker/sitl.Dockerfile \
    --build-arg BASE_TAG=orynth-base:dev -t orynth-sitl:dev .
```

`sitl_swarm.sh` (step 2.3) builds both on demand, so this step is optional.

### 2.2 — Unit gate

The formation geometry, `MavrosAdapter`, the `swarm_server` orchestrator and
the SITL launcher / world builder are all unit-tested with no SITL:

```bash
$ make test
```

Expected: `48 tests, 0 errors, 0 failures` at Phase 2 (the cumulative suite —
22 at Phase 1, 48 at Phase 2; the Phase 2.5a leader-follow tests raise it to 55).

### 2.3 — Run the swarm acceptance gate

```bash
$ make swarm-smoke        # or: bash scripts/bringup/sitl_swarm.sh
```

Builds images if needed, cold-starts the headless five-drone stack, then drives
`swarm_server`: `/swarm/takeoff` → `/swarm/engage_formation diamond` → 60 s
hold → `/swarm/land`. It asserts the diamond drift converges under 0.5 m mean
(PLAN § D, Phase 2) and tears the stack down. Exit 0 = pass.

### 2.4 — Bring up the swarm with the Gazebo GUI

```bash
$ make swarm-up
```

Layers `compose.swarm.gui.yaml` over `compose.swarm.yaml`: the `sim` container
switches to Gazebo Harmonic (`SWARM_GAZEBO=1`), the X11 socket and `/dev/dri`
are mounted, and `xhost +local:root` is granted. A Gazebo window opens with
five `iris` drones. Requires a running X server (any Linux desktop session).

### 2.5 — Foxglove operator layout

With the swarm up, connect Foxglove Studio to `ws://localhost:8765` and import
`ros2_ws/src/swarm_bringup/config/operator.json` — it shows all five drones:
`/swarm/status`, live poses in 3D, and per-drone altitude.

### 2.6 — Drive the swarm by hand

The `swarm_server` services are plain ROS 2 services — drive them from the
companion container:

```bash
$ docker compose -f docker/compose.swarm.yaml exec companion bash -lc '
    source /opt/ros/humble/setup.bash && source /opt/overlay/setup.bash
    ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff "{altitude_m: 5.0}"
    ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation \
      "{formation_name: diamond, spacing_m: 4.0, heading_deg: 0.0}"
    ros2 service call /swarm/land std_srvs/srv/Trigger "{}"
  '
```

Formations: `diamond`, `vee`, `column`, `line`. A single drone is detached from
the formation with `/swarm/drone_<N>/manual_goto`.

### 2.7 — Teardown

```bash
$ make swarm-down
```

### 2.8 — What CI runs

| Workflow | Reproduces locally as |
|---|---|
| `sitl_smoke.yml` (`sitl-5-drone-swarm`, nightly) | step 2.3 (`make swarm-smoke`) |
| `unit.yml` | step 2.2 (`make test`) |

The five-drone smoke runs nightly only; PR CI stays single-drone for the
<8 min budget (PLAN § D).

---

## Phase 2.5 — Leader-Follow Demo

A two-stage milestone (PLAN § D, Phase 2.5; ADR 0008): **2.5a** rehearses
leader-follow in the SITL swarm; **2.5b** flies it on real airframes. The
operator manipulates the leader (`drone_0`); the followers shadow its *live*
pose, holding a diamond and tracking it as it moves.

> **Shortcut:** `make leaderfollow-smoke` runs the 2.5a acceptance gate.

### 2.5a.1 — Unit gate

```bash
$ make test
```

Expected: `55 tests, 0 errors, 0 failures` — the cumulative suite; the Phase
2.5a leader-follow + watchdog tests bring it from 48 to 55.

### 2.5a.2 — Run the leader-follow acceptance gate

```bash
$ make leaderfollow-smoke    # or: bash scripts/bringup/leaderfollow_sitl.sh
```

Cold-starts the headless five-drone swarm, then drives `swarm_server`:
`/swarm/takeoff` → `/swarm/follow_leader` (engage) → flies the leader with
`/swarm/drone_0/manual_goto` while the four followers track the diamond →
exercises the leader-pose watchdog → disengage → `/swarm/land`. Asserts the
settled follower drift stays under 0.5 m mean and that the watchdog engages on
a simulated leader-pose dropout. Exit 0 = pass.

### 2.5a.3 — Drive leader-follow by hand

With the swarm up (`make swarm-up` for the Gazebo GUI):

```bash
$ docker compose -f docker/compose.swarm.yaml exec companion bash -lc '
    source /opt/ros/humble/setup.bash && source /opt/overlay/setup.bash
    ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff "{altitude_m: 5.0}"
    ros2 service call /swarm/follow_leader swarm_msgs/srv/FollowLeader \
      "{enable: true, formation_name: diamond, spacing_m: 6.0}"
    ros2 service call /swarm/drone_0/manual_goto swarm_msgs/srv/ManualGoto \
      "{target: {x: 15.0, y: 0.0, z: 5.0}}"
    ros2 service call /swarm/follow_leader swarm_msgs/srv/FollowLeader "{enable: false}"
    ros2 service call /swarm/land std_srvs/srv/Trigger "{}"
  '
```

The watchdog is exercised without a real dropout via `ros2 param set
/swarm_server simulate_leader_dropout true` (then `false`). Foxglove's
`demo.json` layout shows the live per-follower formation error.

### 2.5b — Hardware demo

The on-hardware flight runs on the Jetson Nanos — one drone per Jetson. Full
setup and the `/swarm/*` control surface are in
`docs/runbooks/jetson_swarm_operations.md`; the flight procedure (condensed
safety gate, roles, abort triggers, sign-off) is `docs/runbooks/first_flight.md`.
Per-Jetson summary:

```bash
$ make demo-up DRONE_ID=0      # leader Jetson — MAVROS + Foxglove + swarm_server
$ make demo-up DRONE_ID=1      # follower Jetson — MAVROS  (repeat for 2..4)
$ make demo-check              # swarm-wide preflight health gate (leader Jetson)
$ make demo-down DRONE_ID=<N>  # teardown, per Jetson
```

### 2.5 — What CI runs

| Workflow | Reproduces locally as |
|---|---|
| `sitl_smoke.yml` (`sitl-5-drone-swarm`, nightly) | step 2.5a.2 (`make leaderfollow-smoke`) |
| `unit.yml` | step 2.5a.1 (`make test`) |

The leader-follow gate runs in the same nightly job as the Phase 2 swarm smoke.
2.5b is a hardware flight — no CI gate.

---

## Appendix A — How the Phase 0 pins were originally resolved

These produced the values committed in `digests.lock`, `orynth.repos`, and
`requirements.txt`. Re-run them when refreshing a pin (ADR 0007, quarterly).

**Docker base image digests** (manifest-list digest, so multi-arch resolves):

```bash
$ docker buildx imagetools inspect ros:humble-ros-base-jammy \
    --format '{{.Manifest.Digest}}'
$ docker buildx imagetools inspect nvcr.io/nvidia/l4t-jetpack:r36.3.0 \
    --format '{{.Manifest.Digest}}'
```

**External repo git SHAs** (one per entry in `orynth.repos`):

```bash
$ git ls-remote https://github.com/ArduPilot/ardupilot.git refs/tags/Copter-4.5.7
$ git ls-remote https://github.com/hku-mars/FAST_LIO.git HEAD
# ...repeat for each repository URL
```

**pip package hashes** (`--require-hashes` needs sdist + wheel sha256):

```bash
$ pip download pexpect==4.9.0 --no-deps --no-binary :none: -d /tmp/pins
$ pip download pexpect==4.9.0 --no-deps -d /tmp/pins
$ pip hash /tmp/pins/pexpect-4.9.0*
```

---

## Appendix B — Git workflow

```bash
$ git add -A
$ git commit -m "..."        # commits as dev.markovic@protonmail.com
$ git push origin main
```

> Commits on this repo must use the `Nikola-code-ai` identity
> (`dev.markovic@protonmail.com`). The global git config is already set to it;
> do not override per-commit.

---

## Later phases

Phase 3+ command sequences (YOLO human detection, LiDAR mapping, autonomous
search, HIL, field deployment) are added here as each lands. See
`docs/runbooks/` for operational runbooks (`sitl_swarm_dev.md`,
`jetson_swarm_operations.md`, `first_flight.md`), `WORKFLOW.md` for current
phase status, and `PLAN.md` § D for the roadmap.
