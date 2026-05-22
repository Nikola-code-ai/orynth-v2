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

```bash
docker compose -f docker/compose.swarm.yaml up
```

Sends 5 SITL instances on ports `5760+N*10` (master) and `14550+N*10` (UDP). See `swarm_sim/sitl_launcher.py`.

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
