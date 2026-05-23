# Jetson swarm operations — setup and control

How to set up and operate Orynth v2 on the **Jetson Nano companion computers**:
one drone on a bench, or the full five-drone leader-follow swarm. This is the
operator's master guide for Phase 2.5b — what runs where, how to bring it up,
and how to command it.

> **Scope.** Day-to-day operations and the command surface. The *flight*
> procedure — safety gate, roles, aborts, sign-off — is
> [`first_flight.md`](first_flight.md). The raw bench link test (pure
> `pymavlink`, no ROS) is [`../../scripts/hardware/README.md`](../../scripts/hardware/README.md).
> The leader-follow design rationale is [ADR 0008](../adr/0008-leader-follow-demo-integration.md).

---

## 1. Topology — what runs where

Each drone carries **one Jetson Nano** wired to **one ArduPilot flight
controller** over serial. The Jetsons share a WiFi LAN and one ROS 2 graph
(`ROS_DOMAIN_ID=42`, Cyclone DDS).

```
   drone_0 Jetson  (LEADER / ground hub)        drone_1..4 Jetsons (followers)
   ├─ MAVROS  /drone_0/mavros/*                 ├─ MAVROS /drone_<N>/mavros/*
   ├─ Foxglove bridge   :8765                   └─ (MAVROS only)
   └─ swarm_server  →  /swarm/* services
            │                                          │
            └──────────── Cyclone DDS WiFi LAN ─────────┘
                          ROS_DOMAIN_ID = 42
   Operator laptop: Mission Planner / QGC (MAVLink safety) + Foxglove (ROS view)
```

- **Every Jetson** runs one namespaced MAVROS instance against its FC.
- **The leader's Jetson (drone_0)** additionally runs the Foxglove bridge and
  `swarm_server` — the orchestrator that drives all five drones. It is the
  "ground hub": all `/swarm/*` service calls go here.
- `swarm_server` reaches every follower's MAVROS over the DDS LAN — there is no
  MAVLink mesh between flight controllers (ADR 0008).

One Jetson = one `DRONE_ID` (0..4). `SYSID_THISMAV = DRONE_ID + 1` on the FC,
MAVROS `tgt_system = DRONE_ID + 1`, namespace `/drone_<DRONE_ID>` — all three
must agree (`PLAN.md` § G).

---

## 2. Per-Jetson one-time setup

Do this once on **each** Jetson. Steps 2.1–2.4 are also covered, with wiring
detail and troubleshooting, in
[`../../scripts/hardware/README.md`](../../scripts/hardware/README.md).

### 2.1 Confirm the board

```sh
cat /etc/nv_tegra_release      # expect: # R36 (release), REVISION: 3.x
```

`R36` (JetPack 6 / L4T r36) → the arm64 base image
(`FROM nvcr.io/nvidia/l4t-jetpack:r36.3.0`) runs as-is. `R32` (original Nano,
JetPack 4) → stop; the base image needs an r32 target. See `scripts/hardware/README.md`
Step A.

### 2.2 Clone the repo

```sh
git clone https://github.com/Nikola-code-ai/orynth-v2.git ~/orynth-v2
cd ~/orynth-v2/v2
```

### 2.3 Free and wire the serial port

The 40-pin header UART is `/dev/ttyTHS1`. Release it from the console getty:

```sh
sudo systemctl stop nvgetty && sudo systemctl disable nvgetty
sudo lsof /dev/ttyTHS1        # expect no output
```

Wire **Jetson UART ↔ FC TELEM**, TX/RX crossed, GND common, **no +5V** into the
Jetson (3 wires only — see `scripts/hardware/README.md` Step 3).

### 2.4 Load the ArduPilot demo parameters

On each FC load `config/ardupilot_params/demo_common.parm` then the matching
`drone_<N>.parm`, and reboot the FC. This sets the geofence, failsafes, GUIDED
tuning, companion telemetry stream rates, and the **distinct system id**. Full
instructions and the values to review for your hardware:
[`../../config/ardupilot_params/README.md`](../../config/ardupilot_params/README.md).

Verify per drone:

```sh
python3 scripts/hardware/fc_link_test.py --port /dev/ttyTHS1 --baud 57600
```

### 2.5 Assign a static IP and the DDS peer list

Give each Jetson a fixed LAN address — the scheme the Cyclone DDS template
assumes is `192.168.42.10` + `DRONE_ID` (`.10`=drone_0 … `.14`=drone_4), GCS
`.1`.

WiFi access points usually drop multicast, so DDS discovery needs an explicit
peer list. Per Jetson, copy the template and fill it in:

```sh
cp config/networks/cyclonedds_drone_template.xml \
   config/networks/cyclonedds_drone_$DRONE_ID.xml
# edit: set NetworkInterfaceAddress to the WiFi iface (e.g. wlan0) and list
# every drone + GCS IP under <Peers> (the template is pre-populated for
# 192.168.42.10-14 + .1 — adjust to your LAN).
```

It is consumed by `compose.demo.yaml` via `CYCLONEDDS_URI` (§ 5).

### 2.6 Build the base image

Native arm64 build — slow the first time:

```sh
make base       # builds orynth-base:dev for this board
```

---

## 3. Single drone — bring up

One Jetson, namespaced as `/drone_0`. Useful for bench work and for verifying a
drone before adding it to the swarm.

```sh
cd ~/orynth-v2/v2
bash scripts/bringup/demo_swarm.sh up 0
```

`up 0` runs `docker/compose.demo.yaml` with `DRONE_ID=0` and (because it is
drone_0) `WITH_SWARM_SERVER=1`, so this single Jetson gets MAVROS + Foxglove +
`swarm_server`. `--wait` blocks until the container healthcheck confirms a
**live MAVROS↔FC link** (`/drone_0/mavros/state` `connected: true`).

Verify the link:

```sh
docker exec -it orynth-demo-0 bash -lc \
  'source /opt/ros/humble/setup.bash && ros2 topic echo --once /drone_0/mavros/state'
```

> The simplest possible link test — no ROS, no containers — is the bench script
> `scripts/hardware/fc_link_test.py` (`scripts/hardware/README.md` Part 1). Use
> it first if the container never reaches healthy.

---

## 4. Single drone — control

### 4.1 Via the MAVLink GCS — Mission Planner (or QGroundControl)

Connect the GCS to the FC over a UDP MAVLink endpoint or its own telemetry
radio. The GCS owns arming, flight modes, parameters, geofence and RTL — for a
single bench drone this is the primary control path: arm, take off, fly, land
from the GCS.

- **Mission Planner** (primary) — ArduPilot's first-party reference GCS. Pick
  the COM / UDP port and baud at the top-right and click **Connect**; deepest
  Copter parameter and calibration coverage, plus a built-in Swarm screen.
- **QGroundControl** (alternative) — the cross-platform choice when the operator
  laptop runs Linux or macOS; auto-connects on a detected link.

### 4.2 Via the ROS service surface

`demo_swarm.sh up 0` already started `swarm_server`. With `DRONE_COUNT=1` it
orchestrates just this drone — the same `/swarm/*` services as the swarm, scoped
to one airframe:

```sh
# inside the container, both overlays sourced:
docker exec -it orynth-demo-0 bash -lc 'source /opt/ros/humble/setup.bash; \
  source /opt/overlay/setup.bash; \
  ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff "{altitude_m: 3.0}"'
```

To run `swarm_server` against one drone, bring the Jetson up with
`DRONE_COUNT=1` (`DRONE_COUNT=1 bash scripts/bringup/demo_swarm.sh up 0`).

The full service surface is § 6.

---

## 5. The swarm — bring up

Five Jetsons, one ROS graph. **Leader first.**

On the leader Jetson (drone_0):

```sh
cd ~/orynth-v2/v2
export CYCLONEDDS_URI=file:///workspace/config/networks/cyclonedds_drone_0.xml
bash scripts/bringup/demo_swarm.sh up 0      # MAVROS + Foxglove + swarm_server
```

On **each** follower Jetson (drone_1 … drone_4), with that drone's id:

```sh
cd ~/orynth-v2/v2
export CYCLONEDDS_URI=file:///workspace/config/networks/cyclonedds_drone_1.xml
bash scripts/bringup/demo_swarm.sh up 1      # MAVROS only
```

`CYCLONEDDS_URI` points at the per-drone peer config from § 2.5 (the path is the
in-container mount `/workspace/config/...`). `compose.demo.yaml` uses
`network_mode: host` so the Jetsons discover each other over the physical WiFi.

Each `up` blocks until *that* drone's FC link is live. Then run the swarm-wide
preflight gate from the leader Jetson:

```sh
bash scripts/bringup/demo_swarm.sh preflight
```

It polls every drone and blocks until all report a **live FC link**, an **EKF
global origin** (GPS lock), and **battery > 90%**, then prints `PREFLIGHT PASS`.
This is the hardware health gate `first_flight.md` § 4 depends on.

`make` shortcuts: `make demo-up DRONE_ID=<N>`, `make demo-check`,
`make demo-down DRONE_ID=<N>`.

Connect the operator laptop's Foxglove Studio to `ws://<leader-jetson-ip>:8765`
and load `ros2_ws/src/swarm_bringup/config/demo.json` — leader + follower poses,
live `/swarm/status`, and the per-follower formation-error plot.

---

## 6. The swarm — control

All `/swarm/*` services are advertised by `swarm_server` on the leader Jetson.
Call them from inside `orynth-demo-0` with both overlays sourced. A convenience
shell:

```sh
swarm() { docker exec -it orynth-demo-0 bash -lc \
  "source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash; ros2 $*"; }
```

| Service | Type | Purpose |
|---------|------|---------|
| `/swarm/takeoff` | `swarm_msgs/SwarmTakeoff` | Coordinated connect → GUIDED → arm → takeoff, all drones. |
| `/swarm/land` | `std_srvs/Trigger` | Coordinated land + disarm, all drones. |
| `/swarm/engage_formation` | `swarm_msgs/SetFormation` | Hold a **static** formation about a fixed centroid (Phase 2). |
| `/swarm/follow_leader` | `swarm_msgs/FollowLeader` | **Live leader-follow** — followers track drone_0's moving pose (Phase 2.5). |
| `/swarm/drone_<N>/manual_goto` | `swarm_msgs/ManualGoto` | Detach one drone and fly it to a point. |

Examples:

```sh
swarm service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff '{altitude_m: 5.0}'

# static diamond, 6 m spacing, facing East
swarm service call /swarm/engage_formation swarm_msgs/srv/SetFormation \
  '{formation_name: diamond, spacing_m: 6.0, heading_deg: 0.0}'

# live leader-follow — followers shadow drone_0's live pose
swarm service call /swarm/follow_leader swarm_msgs/srv/FollowLeader \
  '{enable: true, formation_name: diamond, spacing_m: 6.0}'

# fly one drone independently (detaches it from the formation)
swarm service call /swarm/drone_2/manual_goto swarm_msgs/srv/ManualGoto \
  '{target: {x: 10.0, y: 0.0, z: 5.0}}'

swarm service call /swarm/follow_leader swarm_msgs/srv/FollowLeader '{enable: false}'
swarm service call /swarm/land std_srvs/srv/Trigger '{}'
```

Formations: `diamond`, `vee`, `column`, `line`. `swarm_server` publishes
`/swarm/status` (phase, formation, watchdog/emergency) and `/swarm/formation_error`
(per-drone horizontal error) — both on the `demo.json` layout.

### Bench / GUIDED-leader teleop

For bench dev or any scenario where the **leader is companion-controlled**
(GUIDED, not RC-flown by a safety pilot), `leader_keyboard` is the operator's
interactive tool — it nudges `drone_0`'s `manual_goto` target by `current_pose
+ step` on each keypress instead of asking the operator to compose a service
call per move:

```sh
# Run on the leader's Jetson (drone_0) — needs an interactive TTY.
ros2 run swarm_control leader_keyboard
```

Keys: `w/a/s/d` translate the leader 2 m N/W/S/E (uppercase = 5 m), `r/f`
±1 m altitude, space = hold, `h` = help, `q` or Ctrl-C to quit. The four
followers track via the existing `/swarm/follow_leader` loop.

> **Do not use during the production demo.** In the standard Phase 2.5b
> sequence the leader is hand-flown by a safety pilot in LOITER — RC mode
> authority intentionally removes the leader from companion control, and
> calling `manual_goto` on it would fight the pilot. Reserved for bench tests
> and any future GUIDED-leader variant.

To activate the formation heading-lock that prevents the diamond rotating
around the leader as ArduPilot yaws toward goto targets, ensure
`FORMATION_LOCK_HEADING=1` is set in `compose.demo.yaml` (it's the default).

---

## 7. The leader-follow demo, end to end

On hardware the **leader is RC-flown by a safety pilot**; the followers are
autonomous. The followers track the leader's pose regardless of the leader's
flight mode — `/swarm/follow_leader` only *reads* drone_0's pose, it never
commands it.

1. `/swarm/takeoff` — all drones lift to a 5 m GUIDED hover.
2. The leader's safety pilot switches the leader to **LOITER**. RC mode
   authority removes the leader from companion control — it is now hand-flown.
3. `/swarm/follow_leader {enable: true, formation_name: diamond, spacing_m: 6.0}`
   — the four followers form the diamond around the leader's live pose.
4. The leader pilot flies; the followers track. Watch `/swarm/formation_error`
   on Foxglove.
5. `/swarm/follow_leader {enable: false}`; leader lands on RC; `/swarm/land`
   for the followers.

The full procedure with the safety gate, roles, and aborts is
[`first_flight.md`](first_flight.md). Rehearse it in SITL first:
`make leaderfollow-smoke` (Phase 2.5a) or `make swarm-up` for the on-screen
Gazebo version.

---

## 8. Failsafes and the leader-pose watchdog

Three independent layers protect the swarm:

- **Leader-pose watchdog** (`swarm_server`). If the leader's pose goes stale —
  WiFi/DDS dropout — for longer than `leader_pose_timeout_s` (default 1.5 s),
  the followers **freeze on the last good leader reference** (hold position)
  instead of chasing a stale setpoint, and `/swarm/status` raises the emergency.
  Exercise it without a real dropout:
  `ros2 param set /swarm_server simulate_leader_dropout true` (then `false`).
- **ArduPilot GCS failsafe** (`FS_GCS_ENABLE 1`). If a follower loses the
  MAVLink heartbeat from its companion, its FC triggers RTL.
- **Safety pilot RC override.** One pilot per drone, transmitter live. Switching
  to LOITER/LAND on RC overrides every companion command — the last line of
  defence (`first_flight.md` § 6).

Geofence and battery failsafes are set by `demo_common.parm` (§ 2.4).

---

## 9. Teardown

Per Jetson:

```sh
bash scripts/bringup/demo_swarm.sh down <DRONE_ID>     # or: make demo-down DRONE_ID=<N>
```

Power the flight controllers down only after the companions have stopped.

---

## 10. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `up` healthcheck times out | MAVROS never reached `connected: true`. Run `scripts/hardware/fc_link_test.py` — TX/RX swapped, baud ≠ `SERIALx_BAUD`, console getty holding the port, or FC unpowered. |
| Container exits / image won't run | L4T mismatch — re-check § 2.1 (`/etc/nv_tegra_release`). |
| `preflight` stuck on a follower | That drone has no link, no EKF global origin (poor GPS), or battery ≤ 90%. The line names which check failed. |
| `swarm_server` sees only some drones | DDS discovery — confirm `CYCLONEDDS_URI` peer list has every IP, all Jetsons on `ROS_DOMAIN_ID=42`, `network_mode: host` in effect. |
| `/swarm/follow_leader` rejected "no pose yet" | The leader is not airborne / not publishing pose — take off first. |
| Followers do not track the leader | Leader pose stale → check the watchdog/emergency on `/swarm/status`; check the WiFi link to the leader Jetson. |
| Two MAVROS instances collide / one drops | Duplicate system id — confirm each FC's `SYSID_THISMAV = DRONE_ID + 1` (§ 2.4). |
| `/drone_<N>/mavros/local_position/pose` silent | FC not streaming — the `SRn_*` rates in `demo_common.parm` target the wrong serial port; set them for the port the Jetson uses. |

---

## 11. Command quick reference

| Action | Command |
|--------|---------|
| Build base image (per Jetson, once) | `make base` |
| Bring up this Jetson's drone | `make demo-up DRONE_ID=<0-4>` |
| Swarm preflight gate (leader Jetson) | `make demo-check` |
| Tear down this Jetson | `make demo-down DRONE_ID=<0-4>` |
| Bench link test (no ROS) | `python3 scripts/hardware/fc_link_test.py --port /dev/ttyTHS1 --baud 57600` |
| Props-off motor test | `python3 scripts/hardware/motor_test.py --port /dev/ttyTHS1 --motor 1 --throttle 8` |
| Rehearse leader-follow in SITL | `make leaderfollow-smoke` |
| Leader-follow in Gazebo (on screen) | `make swarm-up` |

---

## 12. See also

- [`first_flight.md`](first_flight.md) — the Phase 2.5b flight procedure.
- [`../../scripts/hardware/README.md`](../../scripts/hardware/README.md) — bench link + motor test.
- [`../../config/ardupilot_params/README.md`](../../config/ardupilot_params/README.md) — demo parameters.
- [`sitl_swarm_dev.md`](sitl_swarm_dev.md) — the SITL swarm dev stack.
- [ADR 0008](../adr/0008-leader-follow-demo-integration.md) — leader-follow design.
- `COMMANDS.md` — the full reproducible command reference.
