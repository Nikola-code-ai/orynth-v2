# Runbook: SITL swarm dev loop

Quick-start for a contributor working on swarm logic without touching real hardware.

## Prerequisites

- Linux workstation (Ubuntu 22.04 recommended; any host with Docker is fine).
- Docker 24+ with `buildx`.
- 16 GB RAM, 8 cores recommended for 5-drone SITL.
- (Optional) NVIDIA GPU with `nvidia-container-toolkit` if you want GPU-accelerated YOLO in dev.

## First-time setup

```bash
git clone <repo>
cd v2
git lfs install
git lfs pull

# Pin sentinels in orynth.repos must be replaced before first build (ADR 0007).
# scripts/build/refresh_pins.sh handles this; until then, manually populate.
bash scripts/build/refresh_pins.sh  # produces a PR-able diff

# Build the base image.
docker buildx build -f docker/base.Dockerfile -t orynth-base:dev .
```

## Phase 1 — single-drone SITL

Build the images once (the SITL image compiles ArduPilot from source — slow the
first time, cached after):

```bash
make base          # orynth-base:dev
make sitl-smoke    # builds orynth-sitl:dev on demand, then runs the smoke test
```

`make sitl-smoke` cold-starts the stack, flies the acceptance mission
(arm → GUIDED takeoff 5 m → waypoint (10,0,5) → land, all via `MavrosAdapter`)
and tears down. Expect exit 0.

To keep the stack up for interactive work / Foxglove:

```bash
make sitl-up       # docker compose up --wait (SITL + MAVROS + Foxglove bridge)
# connect Foxglove Studio to ws://localhost:8765
make sitl-down     # tear down
```

The adapter contract is also unit-tested without SITL — `make test`. Record the
acceptance bag (`accept/phase1.mcap`) with `make sitl-accept`. Full command
reference: `COMMANDS.md` § Phase 1.

## Phase 2 — 5-drone SITL swarm

The swarm runs five ArduPilot SITL instances + five namespaced MAVROS +
`swarm_server`. It has two interchangeable simulation backends — both drive the
*same* `swarm_server` / formation stack:

```bash
make swarm-smoke    # headless pure-SITL acceptance gate (takeoff/diamond/land)
make swarm-up       # 5 drones in Gazebo Harmonic, GUI on the host display
make swarm-down     # tear down
```

`make swarm-smoke` (= `scripts/bringup/sitl_swarm.sh`) cold-starts the headless
stack, drives `/swarm/takeoff` → `/swarm/engage_formation diamond` → 60 s hold →
`/swarm/land`, and asserts the diamond drift converges under 0.5 m mean. This is
the Phase 2 acceptance gate and the nightly CI job.

`make swarm-up` layers `docker/compose.swarm.gui.yaml`: the `sim` container runs
Gazebo Harmonic with five `iris` drones and the GUI on screen. Connect Foxglove
Studio to `ws://localhost:8765` and import
`ros2_ws/src/swarm_bringup/config/operator.json` to watch all five.

SITL instance N exposes MAVLink TCP on `5760+N*10`. `swarm_server` services:
`/swarm/takeoff`, `/swarm/land`, `/swarm/engage_formation`,
`/swarm/drone_<N>/manual_goto`. See `swarm_sim/sitl_launcher.py` and
`swarm_control/swarm_server_node.py`; full command reference in
`COMMANDS.md` § Phase 2.

## Common gotchas (swarm)

- **Gazebo GUI does not open (`make swarm-up`)**: needs an X server and
  `/dev/dri`. `make swarm-up` runs `xhost +local:root`; if it still fails,
  review headless via Foxglove instead — the swarm stack is identical.
- **`companion` slow to go healthy**: it builds the `swarm_msgs` IDL + overlay
  at container start (~60–90 s) before the five MAVROS instances launch.

## Adding a Python dependency

Per ADR 0007:

1. Add `pkg==version` to `docker/requirements.txt`.
2. Run `pip-compile --generate-hashes` (via `scripts/build/refresh_pins.sh`) to update hashes.
3. Rebuild the base image.
4. Commit the lockfile diff alongside the code change.

## Adding an external ROS dependency

1. Add to `orynth.repos` with a real git SHA (not the placeholder zeros).
2. Add the runtime `<depend>` to the consuming package's `package.xml`.
3. `vcs import ros2_ws/src < orynth.repos`.
4. `colcon build`.

## Common gotchas

- **`docker compose` says "no buildx"**: install via `apt-get install docker-buildx-plugin`.
- **GPU passthrough in dev container fails**: install `nvidia-container-toolkit` and add `--gpus all` to compose; not required for Phase 0/1.
- **MAVROS doesn't see SITL**: check `fcu_url` matches `tcp://sitl:5760@`. Hostname `sitl` is the compose service name.
- **CI fails on pin-check but works locally**: pin sentinels (zeros) are present in `orynth.repos`. Run `refresh_pins.sh`.
