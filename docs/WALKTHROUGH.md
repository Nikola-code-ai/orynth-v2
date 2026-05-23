# Orynth v2 — End-to-End Walkthrough

A linear, copy-paste walkthrough for someone setting the repo up for the first
time and exercising every piece of functionality available in simulation.

All commands run from the repo root: `~/Projects/Orynth/v2/`. Commands are
shown bare (no `$` prefix) so you can copy-paste them straight into your
terminal. Where you need a separate terminal window or to switch focus to
Foxglove, it's called out explicitly.

For the reference version of this doc (denser, cross-linked to PLAN/WORKFLOW),
see `COMMANDS.md`. This file is the "hand-holding" version.

---

## 0. What you're about to do

The Orynth stack has three layers, and you'll bring each one up in turn:

1. **Build layer** — a Docker image (`orynth-base:dev`) that contains ROS 2
   Humble plus all our pinned dependencies. Everything else runs inside
   containers built on top of it, so you never need ROS installed on the host.

2. **Sim layer** — ArduPilot SITL (Software In The Loop). Real Copter 4.5.x
   firmware running on your laptop with no physical Pixhawk. Two flavours:
   - **pure-SITL** — ArduPilot's built-in `quad` physics, headless, fast.
     This is what CI runs.
   - **Gazebo Harmonic** — 3D world with `iris` drone models. Pure eye-candy /
     debugging aid, swappable underneath the same MAVROS layer.

3. **Companion layer** — what would run on a Jetson Orin Nano in the field:
   MAVROS (bridges MAVLink ↔ ROS 2 topics), `swarm_server_node` (high-level
   formation services), Foxglove bridge (exposes ROS 2 topics over WebSocket
   on port 8765 for the operator to inspect).

**Foxglove Studio** is just a viewer. It talks to the Foxglove bridge over
WebSocket and lets you see live ROS 2 topics — drone poses, battery, MAVROS
state, formation error, etc. Same view you'd get from a real Jetson.

---

## 1. Prerequisites (check once)

Verify each is installed:

```
docker --version
docker buildx version
git --version
python3 --version
```

You want Docker 24+, buildx 0.12+, git 2.30+, Python 3.10+.

Foxglove Studio is a separate desktop app — install from
https://foxglove.dev/download if you don't already have it. You don't need an
account; the free tier with WebSocket connections is enough.

---

## 2. Phase 0 — Build the base image and run unit tests

This step proves the build pipeline works. Nothing flies; we're just compiling
the ROS 2 workspace inside a container and running unit tests against the
adapter contract (no live simulator).

### 2.1 Build the base image (3–6 min on a warm cache)

```
make base
```

What's happening: `docker buildx build` produces `orynth-base:dev`, a ~3.8 GB
image containing ROS 2 Humble, MAVROS, our Python deps, and the build
toolchain. Every later container inherits from it.

### 2.2 Build the ROS 2 workspace and run unit tests

```
make test
```

What's happening: spawns an ephemeral container from `orynth-base:dev`, mounts
the repo, runs `colcon build` then `colcon test` over every package except
`swarm_hardware` (which only builds on real Jetson hardware). You should see
something like "55 tests, 0 failures" at the end.

### 2.3 Run the lint suite

```
make lint
```

What's happening: creates a Python venv at `/tmp/orynth-pc-venv`, installs
`pre-commit`, runs every configured hook (ruff, mypy, yamllint, Docker `FROM`
pin check, etc.). All hooks should report `Passed`.

If 2.1, 2.2, and 2.3 all pass: build pipeline is healthy. Move on.

---

## 3. Phase 1 — Single drone in SITL

One ArduPilot SITL drone + MAVROS + Foxglove bridge. This is the smallest
end-to-end pipeline. You already did `make sitl-up` and connected Foxglove
earlier — this section walks through everything you can actually *do* with it.

### 3.1 Headless acceptance mission (the CI gate)

```
make sitl-smoke
```

What's happening: cold-starts the SITL stack, runs `swarm_control.sitl_mission`
which commands the drone through GUIDED → arm → takeoff 5 m → fly to a
waypoint → land. Asserts altitude, position, and disarm. Exit code 0 = pass.
Takes about 90 seconds. The stack tears itself down at the end.

### 3.2 Same mission, but record an MCAP log

```
make sitl-accept
```

What's happening: identical to `sitl-smoke` but with `SMOKE_RECORD=1`, which
also records every ROS 2 topic into `accept/phase1.mcap`. You can open that
file in Foxglove later for offline inspection. The file is gitignored.

### 3.3 Interactive: bring the stack up and poke at it

```
make sitl-up
```

What's happening: starts two long-running containers via
`docker/compose.dev.yaml` — `sitl` (the ArduPilot simulator) and `companion`
(MAVROS + Foxglove bridge). Comes back to the prompt once both pass their
health checks. Foxglove bridge is now listening on `ws://localhost:8765`.

**Now open Foxglove Studio**, click "Open connection", choose "Foxglove
WebSocket", URL `ws://localhost:8765`, click Open. You should see ROS 2 topics
appear in the left panel — `/mavros/state`, `/mavros/local_position/pose`,
etc.

Drive the drone by hand from a second terminal:

```
docker exec -it orynth-companion bash
```

Then inside that shell:

```
source /opt/ros/humble/setup.bash
source /opt/overlay/setup.bash
ros2 topic list
ros2 topic echo /mavros/state
```

(Exit the shell with `exit` or `Ctrl-D` — the stack keeps running.)

### 3.4 Tear it down

```
make sitl-down
```

---

## 4. Phase 2 — 5-drone SITL swarm

Same companion layer, but now five drones at once. The high-level
`swarm_server_node` exposes services like `/swarm/takeoff`,
`/swarm/engage_formation`, `/swarm/land` that fan out to all drones.

### 4.1 Headless acceptance mission

```
make swarm-smoke
```

What's happening: cold-starts 5 pure-SITL instances + companion, then drives
`/swarm/takeoff` → `/swarm/engage_formation diamond` → 60 s hold →
`/swarm/land`. Asserts the diamond formation error stays under 0.5 m mean.
Takes 2–3 minutes. Headless — no Gazebo.

### 4.2 On-screen swarm with Gazebo GUI

This is the one you asked about — where you finally see the 3D world.

```
make swarm-up
```

What's happening: same companion layer, but the SITL backend is swapped for
Gazebo Harmonic with 5 `iris` models in a shared world. `xhost +local:root`
opens your X server to the container so Gazebo can pop up a GUI window. The
stack comes up detached; you get your prompt back.

You should see:
- A Gazebo window with five drones sitting on the ground in a row.
- Foxglove bridge available again at `ws://localhost:8765`.

**In Foxglove**: connect to `ws://localhost:8765`, then File → Import layout
→ pick `ros2_ws/src/swarm_bringup/config/operator.json` for the prebuilt
operator panel layout.

Now drive the swarm. From a second terminal:

```
docker compose -f docker/compose.swarm.yaml exec companion bash
```

Inside that shell, source the overlays:

```
source /opt/ros/humble/setup.bash
source /opt/overlay/setup.bash
```

Take off to 5 metres:

```
ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff "{altitude_m: 5.0}"
```

Engage diamond formation, 4 m spacing:

```
ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation "{formation_name: diamond, spacing_m: 4.0, heading_deg: 0.0}"
```

Try the other formations (`vee`, `column`, `line`):

```
ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation "{formation_name: vee, spacing_m: 4.0, heading_deg: 0.0}"
ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation "{formation_name: column, spacing_m: 4.0, heading_deg: 0.0}"
ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation "{formation_name: line, spacing_m: 4.0, heading_deg: 0.0}"
```

Detach a single drone and send it somewhere:

```
ros2 service call /swarm/drone_2/manual_goto swarm_msgs/srv/ManualGoto "{target: {x: 10.0, y: 10.0, z: 5.0}}"
```

Land everyone:

```
ros2 service call /swarm/land std_srvs/srv/Trigger "{}"
```

### 4.3 Tear it down

```
make swarm-down
```

---

## 5. Phase 2.5a — Leader-follow rehearsal

Same 5-drone swarm, but instead of the formation being commanded by waypoints,
followers shadow `drone_0`'s live pose. You move the leader, the diamond moves
with it.

### 5.1 Headless acceptance mission

```
make leaderfollow-smoke
```

What's happening: cold-starts the swarm, runs `/swarm/takeoff` →
`/swarm/follow_leader engage` → drives `drone_0` to a waypoint via
`/swarm/drone_0/manual_goto` → simulates a leader-pose dropout to exercise the
watchdog → disengages → `/swarm/land`. Asserts settled follower drift < 0.5 m
mean and that the watchdog engages on the simulated dropout.

### 5.2 Drive leader-follow by hand

Bring up the swarm with GUI if it isn't already:

```
make swarm-up
```

Exec into the companion as before:

```
docker compose -f docker/compose.swarm.yaml exec companion bash
```

```
source /opt/ros/humble/setup.bash
source /opt/overlay/setup.bash
```

Take off and engage leader-follow with 6 m spacing:

```
ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff "{altitude_m: 5.0}"
ros2 service call /swarm/follow_leader swarm_msgs/srv/FollowLeader "{enable: true, formation_name: diamond, spacing_m: 6.0}"
```

Fly the leader; watch the followers track it:

```
ros2 service call /swarm/drone_0/manual_goto swarm_msgs/srv/ManualGoto "{target: {x: 15.0, y: 0.0, z: 5.0}}"
```

Exercise the watchdog without an actual dropout (the leader will go idle in
the followers' view; they'll hold position):

```
ros2 param set /swarm_server simulate_leader_dropout true
ros2 param set /swarm_server simulate_leader_dropout false
```

Disengage and land:

```
ros2 service call /swarm/follow_leader swarm_msgs/srv/FollowLeader "{enable: false}"
ros2 service call /swarm/land std_srvs/srv/Trigger "{}"
```

In Foxglove, load `ros2_ws/src/swarm_bringup/config/demo.json` instead of
`operator.json` for the per-follower formation-error plot.

### 5.3 Tear it down

```
make swarm-down
```

---

## 6. Phase 2.5b — Hardware demo (not runnable on this laptop)

This phase runs one drone per Jetson Orin Nano against real Pixhawks. It uses
`make demo-up DRONE_ID=<0-4>` on each Jetson, gated by `make demo-check` on
the leader. You can't exercise this without the airframes — the procedure
lives in:

- `docs/runbooks/jetson_swarm_operations.md` — operator setup
- `docs/runbooks/first_flight.md` — flight sequence and abort triggers

---

## 7. Where to look when things go wrong

- **Build broke?** `make clean && make test` from a fresh state. If the base
  image is suspect, `docker image rm orynth-base:dev && make base`.
- **`sitl-up` reports unhealthy?** `docker compose -f docker/compose.dev.yaml logs sitl`
  and `... logs companion`.
- **Foxglove won't connect?** Make sure the stack is actually up
  (`docker ps | grep orynth`) and that port 8765 isn't being blocked by a
  firewall. The bridge is plain WebSocket, no TLS.
- **Gazebo window doesn't appear after `swarm-up`?** Confirm you're on a
  Linux desktop session (X11). `xhost +local:root` is run automatically but
  needs an X server to talk to.
- **Mission fails mid-flight?** `accept/phase1.mcap` (from `make sitl-accept`)
  is the easiest way to debug — open it in Foxglove and scrub through the
  timeline.

Real bugs / past gotchas: `WORKFLOW.md` § "Issues encountered & fixes".

---

## 8. Quick reference — every make target

```
make help            # list all targets with one-line descriptions
make base            # build orynth-base:dev image
make test            # colcon build + colcon test (unit gate)
make lint            # pre-commit on all files
make sitl-up         # Phase 1 stack up (foreground stays detached)
make sitl-smoke      # Phase 1 acceptance mission (auto-tears-down)
make sitl-accept     # sitl-smoke + record accept/phase1.mcap
make sitl-down       # Phase 1 stack down
make swarm-smoke     # Phase 2 acceptance (headless, 5 drones)
make swarm-up        # Phase 2 stack up with Gazebo GUI
make swarm-down      # Phase 2 stack down
make leaderfollow-smoke   # Phase 2.5a acceptance
make demo-up DRONE_ID=N   # Phase 2.5b per-Jetson bringup (hardware)
make demo-check           # Phase 2.5b preflight gate (leader Jetson)
make demo-down DRONE_ID=N # Phase 2.5b per-Jetson teardown
make shell           # interactive shell inside orynth-base
make clean           # wipe colcon build/install/log
```
