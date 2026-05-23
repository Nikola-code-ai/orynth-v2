# Orynth v2 — Command Reference

Step-by-step commands to reproduce and verify each phase. Companion to
[`PLAN.md`](PLAN.md) (what & why) and [`WORKFLOW.md`](WORKFLOW.md) (status).

For the big-picture, picture-rich walkthrough of how everything fits together,
see [`docs/architecture/end_to_end/end_to_end_setup.pdf`](docs/architecture/end_to_end/end_to_end_setup.pdf).

## Conventions

- All commands run from the repo root (`v2/`) unless stated otherwise.
- `$` is a host shell. Nothing drops you into a long-lived container — every
  containerised step is a `docker run --rm` or a `docker compose` service.
  `make shell` is the only interactive container entry point.
- `make help` lists every target.

## Prerequisites

| Tool          | Version | Why |
|---------------|---------|-----|
| Docker Engine | 24+     | base image build, containerised colcon, compose |
| Docker buildx | 0.12+   | multi-arch build, digest resolution |
| git           | 2.30+   | clone, pin resolution |
| Python 3      | 3.10+   | `pre-commit` (in a venv) |

## CI gate map

Every CI workflow has a local one-liner. Reproduce a red CI job by running its
local equivalent.

| Workflow              | When it runs            | Local equivalent       |
|-----------------------|-------------------------|------------------------|
| `lint.yml`            | every push / PR         | `make lint`            |
| `unit.yml`            | every push / PR         | `make test`            |
| `sitl_smoke.yml` (1-drone) | every PR           | `make sitl-smoke`      |
| `sitl_smoke.yml` (5-drone swarm) | nightly      | `make swarm-smoke`     |
| `sitl_smoke.yml` (leader-follow) | nightly      | `make leaderfollow-smoke` |
| `docker_build.yml`    | `main`, docker/ changes | `make base` (amd64 only) |

---

## Phase 0 — Repo scaffold + CI + Docker baseline

Reproducible build / test / lint baseline.

### 1. Clone

```sh
$ git clone https://github.com/Nikola-code-ai/orynth-v2.git
$ cd orynth-v2
```

### 2. Build + test + lint

```sh
$ make base        # ~3-6 min on a warm cache (the image dominates)
$ make test        # colcon build + colcon test inside orynth-base
$ make lint        # pre-commit in a venv
```

Expected: image `orynth-base:dev` (~3.8 GB); the cumulative test suite (3 at
Phase 0, 22 / 48 / 55 as later phases land); every pre-commit hook `Passed`.

### 3. Pin audit

```sh
$ bash scripts/build/refresh_pins.sh
```

Expected: `RESULT: all pins resolvable; digests.lock matches upstream.`
(`ardupilot` reports `AHEAD` — it is pinned to tag `Copter-4.5.7`, behind
upstream HEAD by design.)

### 4. Clean up

```sh
$ make clean       # removes ros2_ws/{build,install,log} via the container
```

> Raw `docker buildx` + `colcon` invocations (what each `make` target wraps)
> are in [Appendix A](#appendix-a--phase-0-raw-commands).

---

## Phase 1 — Single-drone SITL + MAVROS + Foxglove

Brings up one ArduPilot SITL drone and flies an acceptance mission through the
backend-neutral `MavrosAdapter`.

### 1. Run the acceptance gate

```sh
$ make sitl-smoke
```

Builds `orynth-base` + `orynth-sitl` on first run, cold-starts the stack, drives
`swarm_control.sitl_mission` (GUIDED → arm → takeoff 5 m → waypoint → land),
tears down. Exit 0 = pass.

### 2. Record an acceptance bag

```sh
$ make sitl-accept       # writes accept/phase1.mcap (gitignored)
```

Captures `/mavros/state`, `/mavros/local_position/pose`,
`/mavros/setpoint_raw/local`.

### 3. Foxglove + live exploration

```sh
$ make sitl-up           # foreground stack: sitl + companion
$ # connect Foxglove Studio to ws://localhost:8765
$ make sitl-down         # tear down
```

---

## Phase 1.5 — Single-drone hardware bringup

You have a real airframe wired: flight controller on USB or TELEM, RadioMaster
RC bound, Jetson on TELEM1. This phase proves the **Jetson↔FC link** before you
ever touch the swarm. The bench reality of "Mission Planner + RadioMaster on
one drone" still works exactly as before — this layer just lets the companion
talk to the same FC over its own UART.

> **Mission Planner is the primary GCS** for parameters, modes, failsafes, and
> geofence (`docs/architecture/overview.md` and
> `config/ardupilot_params/README.md`). Load the demo params with MP before
> the companion talks to the FC.

### 1. Load demo parameters via Mission Planner

*Config → Full Parameter List → Load from file* → `config/ardupilot_params/demo_common.parm`
→ **Write Params** → repeat for `drone_<N>.parm` → reboot the FC. See
[`config/ardupilot_params/README.md`](config/ardupilot_params/README.md) for the
per-airframe mapping and the warnings about `BATT_*`, `FENCE_*`, and `SERIAL1_*`.

### 2. Bring up MAVROS against the wired FC

```sh
$ make hw-up             # docker compose -f docker/compose.hw.yaml up
$ # Foxglove: connect Studio to ws://localhost:8765
```

The `companion` container talks to the FC on `serial:///dev/ttyTHS1:57600` by
default. Change `FCU_URL` in `compose.hw.yaml` if your wiring differs.

### 3. Verify the link

```sh
$ make hw-check          # runs scripts/hardware/mavros_link_check.sh inside the container
```

The script confirms `/mavros/state` is publishing, the FC reports a system id,
and pose streams are alive. The standalone pymavlink probe is also useful when
MAVROS itself is what you suspect:

```sh
$ python3 scripts/hardware/fc_link_test.py --port /dev/ttyTHS1 --baud 57600
```

### 4. Tear down

```sh
$ make hw-down
```

> No CI gate — this is hardware. Smoke-tested on a single drone before any
> Phase 2.5b swarm flight.

---

## Phase 2 — 5-drone SITL swarm + diamond formation

Brings up five SITL drones and flies a diamond-formation acceptance mission
through `swarm_server_node`. Same `swarm_server` / formation / MAVROS layer for
both backends:

- **pure-SITL** (`arducopter --model=quad`) — headless, frame-clean, fast; what
  the gate and CI run.
- **Gazebo Harmonic** — the 3D world (ADR 0003), for on-screen review.

### 1. Run the acceptance gate

```sh
$ make swarm-smoke
```

Cold-starts the headless 5-drone stack and drives `swarm_server`:
`/swarm/takeoff` → `/swarm/engage_formation diamond` → 60 s hold →
`/swarm/land`. Asserts diamond drift converges under 0.5 m mean. Exit 0 = pass.

### 2. On-screen swarm with the Gazebo GUI

```sh
$ make swarm-up          # 5 iris drones in Gazebo + Foxglove ready
$ # Foxglove: import ros2_ws/src/swarm_bringup/config/operator.json
$ make swarm-down
```

Requires a running X server (any Linux desktop session). `xhost +local:root` is
granted automatically.

### 3. Drive the swarm by hand

With the swarm up, services are plain ROS 2:

```sh
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

---

## Phase 2.5a — Leader-follow SITL rehearsal

The operator manipulates the leader (`drone_0`); followers shadow its *live*
pose, holding a diamond and tracking it as it moves.

### 1. Run the acceptance gate

```sh
$ make leaderfollow-smoke
```

Cold-starts the 5-drone swarm, runs `/swarm/takeoff` → `/swarm/follow_leader`
engage → flies the leader via `/swarm/drone_0/manual_goto` → exercises the
leader-pose watchdog → disengage → `/swarm/land`. Asserts settled follower drift
< 0.5 m mean and that the watchdog engages on a simulated leader-pose dropout.

### 2. Drive leader-follow by hand

With the swarm up (`make swarm-up`):

```sh
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

The watchdog is exercised without a real dropout via
`ros2 param set /swarm_server simulate_leader_dropout true` (then `false`).
Foxglove `demo.json` shows the live per-follower formation error.

### 3. Fly the leader with the keyboard

Once the swarm is up and `/swarm/follow_leader` is engaged, drive `drone_0`
interactively instead of issuing one `manual_goto` per move:

```sh
$ docker exec -it orynth-swarm-companion bash -lc \
    'source /opt/overlay/setup.bash && ros2 run swarm_control leader_keyboard'
```

Each keypress nudges `drone_0` by `current_pose + step` in field-ENU:

| Key       | Action                              |
|-----------|-------------------------------------|
| `w` / `W` | north +2 m / +5 m                   |
| `s` / `S` | south                               |
| `a` / `A` | west +2 m / +5 m                    |
| `d` / `D` | east                                |
| `r` / `R` | up +1 m / +2 m                      |
| `f` / `F` | down                                |
| `space`   | hold (re-send current pose)         |
| `h`       | show keymap                         |
| `q` / Ctrl-C | quit                             |

The `make swarm-up` GUI compose sets `FORMATION_LOCK_HEADING=1`, so the diamond
translates with the leader but never rotates around it — followers stay in their
field-ENU slots even when ArduPilot yaws the leader toward each goto target.

---

## Phase 2.5b — Hardware leader-follow demo

One drone per Jetson. Mission Planner remains the per-airframe GCS; the
companion only drives the autonomous followers. Full procedure (safety gate,
roles, abort triggers, sign-off) is
[`docs/runbooks/first_flight.md`](docs/runbooks/first_flight.md); operator
setup is [`docs/runbooks/jetson_swarm_operations.md`](docs/runbooks/jetson_swarm_operations.md).

### 1. Per-Jetson bringup

On **each** Jetson, picking the correct `DRONE_ID`:

```sh
$ make demo-up DRONE_ID=0    # leader Jetson — MAVROS + Foxglove + swarm_server
$ make demo-up DRONE_ID=1    # follower Jetson — MAVROS only; repeat 2..4
```

### 2. Swarm-wide preflight gate

On the **leader Jetson**:

```sh
$ make demo-check
```

Blocks until every drone reports a live FC link, an EKF global origin, and
battery > 90 %. Prints `PREFLIGHT PASS`. **Do not proceed past a failed
preflight.**

### 3. Fly

The flight sequence (takeoff → engage → leader RC-flown → watchdog → land) is
in [`docs/runbooks/first_flight.md`](docs/runbooks/first_flight.md) § 5. Same
`/swarm/*` services as Phase 2.5a — the only thing that changed is the airframe
underneath.

### 4. Tear down

Per Jetson:

```sh
$ make demo-down DRONE_ID=<N>
```

> No CI gate — this is the hardware acceptance flight.

---

## Appendix A — Phase 0 raw commands

Each step here is what the equivalent `make` target runs. Useful when
debugging a Make target or porting to another build system.

**Base image build** (what `make base` does):

```sh
$ docker buildx build --load -f docker/base.Dockerfile -t orynth-base:dev .
```

Multi-arch (what `docker_build.yml` does on `main` — slow under QEMU, do not
attempt locally without arm64 hardware):

```sh
$ docker buildx build --platform linux/amd64,linux/arm64 \
    -f docker/base.Dockerfile -t orynth-base:multi .
```

**Workspace build + test** (what `make test` does):

```sh
$ docker run --rm -v "$PWD":/workspace -w /workspace/ros2_ws orynth-base:dev \
    bash -c '
      set -e
      colcon build --packages-skip swarm_hardware
      colcon test  --packages-skip swarm_hardware --return-code-on-test-failure
      colcon test-result --verbose
    '
```

**Lint** (what `make lint` does — `pre-commit` in a PEP 668-safe venv):

```sh
$ python3 -m venv /tmp/pc-venv
$ /tmp/pc-venv/bin/pip install pre-commit==3.7.1
$ /tmp/pc-venv/bin/pre-commit run --all-files
```

The lint workflow also rejects unpinned Docker base images. Reproduce that
check directly:

```sh
$ grep -rE "^FROM [^@$]+:[^@]+\s*$" docker/ && echo "UNPINNED FROM" || echo "OK"
```

**Workspace clean** (what `make clean` does):

```sh
$ docker run --rm -v "$PWD":/workspace orynth-base:dev \
    bash -c 'rm -rf /workspace/ros2_ws/build /workspace/ros2_ws/install /workspace/ros2_ws/log'
```

---

## Appendix B — How the Phase 0 pins were originally resolved

These produced the values committed in `digests.lock`, `orynth.repos`, and
`requirements.txt`. Re-run them when refreshing a pin (ADR 0007, quarterly).

**Docker base image digests** (manifest-list digest for multi-arch):

```sh
$ docker buildx imagetools inspect ros:humble-ros-base-jammy \
    --format '{{.Manifest.Digest}}'
$ docker buildx imagetools inspect nvcr.io/nvidia/l4t-jetpack:r36.3.0 \
    --format '{{.Manifest.Digest}}'
```

**External repo git SHAs** (one per entry in `orynth.repos`):

```sh
$ git ls-remote https://github.com/ArduPilot/ardupilot.git refs/tags/Copter-4.5.7
$ git ls-remote https://github.com/hku-mars/FAST_LIO.git HEAD
# ...repeat for each repository URL
```

**pip package hashes** (`--require-hashes` needs sdist + wheel sha256):

```sh
$ pip download pexpect==4.9.0 --no-deps --no-binary :none: -d /tmp/pins
$ pip download pexpect==4.9.0 --no-deps -d /tmp/pins
$ pip hash /tmp/pins/pexpect-4.9.0*
```

---

## Appendix C — Git workflow

```sh
$ git add -A
$ git commit -m "..."        # commits as dev.markovic@protonmail.com
$ git push origin main
```

Commits on this repo must use the `Nikola-code-ai` identity
(`dev.markovic@protonmail.com`). The global git config is already set; do not
override per-commit.

---

## Later phases

Phase 3+ commands (YOLO human detection, LiDAR mapping, autonomous search, HIL,
field deployment) land here as each phase does. See
[`docs/runbooks/`](docs/runbooks/) for operational procedures,
[`WORKFLOW.md`](WORKFLOW.md) for current status, and [`PLAN.md`](PLAN.md) § D
for the roadmap.
