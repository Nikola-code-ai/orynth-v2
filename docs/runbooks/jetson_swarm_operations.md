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
controller** over serial **and** one SiK / RFD900x telemetry radio over USB.
The Jetsons no longer share a ROS 2 graph (ADR 0009): each has its own
`ROS_DOMAIN_ID = 100 + DRONE_ID` and DDS is bound to `lo` only. Cross-drone
traffic rides MAVLink over the radio, via `radio_bridge` (package
`swarm_radio`).

```
   drone_0 Jetson  (LEADER / ground hub)            drone_1 Jetson  (follower)
   ├─ MAVROS  /drone_0/mavros/*  (real FC link)     ├─ MAVROS /drone_1/mavros/*
   ├─ radio_bridge  role=leader                     ├─ radio_bridge role=follower
   │    synthesises /drone_1/mavros/* from radio    │    publishes drone_1 state
   │    forwards swarm_server setpoints to radio    │    receives setpoints
   ├─ Foxglove bridge   :8765                       └─ (no swarm_server here)
   └─ swarm_server  →  /swarm/* services
            │                                                │
            └─── SiK / RFD900x  MAVLink radio (multipoint) ───┘
                 ORYNTH_DRONE_STATE / ORYNTH_SETPOINT /
                 ORYNTH_COMMAND / ORYNTH_ACK / ORYNTH_HEARTBEAT
   Operator laptop: Mission Planner / QGC (MAVLink safety) + Foxglove (ROS view)
```

**Hardware Prerequisites for the Swarm:**
- **SiK / RFD900x radios:** one per Jetson, USB-attached (e.g.
  `/dev/ttyUSB_RFD`). Configure in **multipoint mode**: leader = base node,
  follower(s) = remote nodes. Wiring + firmware procedure in
  [`radio_link_bringup.md`](radio_link_bringup.md).
- **(Optional) WiFi LAN:** still useful for Foxglove and developer SSH into the
  leader Jetson. No longer carries inter-drone traffic. A dropped WiFi has
  zero effect on the formation loop — the radio is what matters now.
- **Power Supply:** The Orin Nanos draw up to 25W under load (YOLO + LIO + max perf). Do **not** power them from the ArduPilot power module. Use a dedicated high-quality 5V/5A+ BEC per Jetson directly wired to the battery.
- **Storage:** Boot from an NVMe SSD, not a microSD card. MicroSD cards will fail quickly under `rosbag2` logging and Docker layer filesystem writes.
- **Time Sync:** Formation tracking benefits from synchronised clocks. The
  `radio_bridge` watchdog uses local monotonic time, but timestamps in
  `/swarm/status` and bag recordings come from the system clock — configure
  `Chrony` (NTP) on the leader Jetson and keep followers within ~50 ms.

- **Every Jetson** runs one namespaced MAVROS instance against its FC **and**
  one `radio_bridge` instance against its radio.
- **The leader's Jetson (drone_0)** additionally runs the Foxglove bridge and
  `swarm_server` — the orchestrator that drives every drone. All `/swarm/*`
  service calls go here. `swarm_server` sees a uniform `/drone_K/mavros/*`
  topic surface for every drone; for follower drones those topics are
  synthesised by the leader-side `radio_bridge` from inbound radio frames.
- There is no MAVLink mesh between flight controllers — radios are on the
  Jetson side, not the FC side (ADR 0009).

One Jetson = one `DRONE_ID` (0..N-1). `SYSID_THISMAV = DRONE_ID + 1` on the FC,
MAVROS `tgt_system = DRONE_ID + 1`, namespace `/drone_<DRONE_ID>` — all three
must agree (`PLAN.md` § G). `ROS_DOMAIN_ID = 100 + DRONE_ID` per Jetson.

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

Wire **Jetson UART ↔ FC serial UART**, TX/RX crossed, GND common, **no +5V**
into the Jetson (3 wires only). Pixhawk-class boards use the labeled `TELEM1`
JST-GH connector; F4-class boards (Matek F405 and similar) use the TX/RX
solder pads of the UART that maps to `SERIAL1` in `demo_common.parm`. See
`scripts/hardware/README.md` Step 3 for the full table.

### 2.4 Load the ArduPilot demo parameters

On each FC load `config/ardupilot_params/demo_common.parm` then the matching
`drone_<N>.parm`, and reboot the FC. This sets the geofence, failsafes, GUIDED
tuning, companion telemetry stream rates, and the **distinct system id**. Full
instructions and the values to review for your hardware:
[`../../config/ardupilot_params/README.md`](../../config/ardupilot_params/README.md).

Verify per drone:

```sh
python3 scripts/hardware/fc_link_test.py --port /dev/ttyTHS1 --baud 921600
```

### 2.5 Set up the SiK / RFD900x radio

Inter-drone traffic rides this radio (ADR 0009). Per Jetson:

1. Plug the radio into a USB port. Confirm a `/dev/ttyUSB*` shows up
   (`ls /dev/ttyUSB*`).
2. Create a stable udev symlink so the device name does not change:

   ```sh
   sudo cp config/udev/99-orynth-rfd900.rules /etc/udev/rules.d/
   sudo udevadm control --reload && sudo udevadm trigger
   ls -l /dev/ttyUSB_RFD                # should now exist
   ```

3. Configure the radio firmware (multipoint mode, distinct `NODEID`,
   matching `NETID`, leader = base node). Full procedure with the AT-command
   sequence is in [`radio_link_bringup.md`](radio_link_bringup.md).
4. **Bench-test the link before any ROS bringup.** Run the two structured
   bench tests in [`radio_bench_tests.md`](radio_bench_tests.md) — link
   chat with no FC, then a props-off motor spin via the radio. These catch
   the high-yield failure modes (`NETID` mismatch, udev rule, FC UART) in
   minutes rather than during full swarm bringup.

No DDS peer list is needed any more. The Cyclone DDS config used on hardware
is `config/networks/cyclonedds_local_only.xml`, which binds DDS to `lo`. The
old `cyclonedds_drone_template.xml` is retained as a legacy fallback only —
do not use it on airframes.

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

N Jetsons, each with its own ROS graph, joined by the SiK/RFD900x radio.
**Leader first.**

On the leader Jetson (drone_0):

```sh
cd ~/orynth-v2/v2
bash scripts/bringup/demo_swarm.sh up 0      # MAVROS + radio_bridge(leader) + Foxglove + swarm_server
```

On **each** follower Jetson, with that drone's id:

```sh
cd ~/orynth-v2/v2
bash scripts/bringup/demo_swarm.sh up 1      # MAVROS + radio_bridge(follower)
```

`compose.demo.yaml` passes the radio device (`/dev/ttyUSB_RFD`) into the
container and configures `radio_bridge` automatically: leader role for
drone_0 (`WITH_SWARM_SERVER=1`), follower role otherwise. DDS is bound to
`lo` per Jetson via `config/networks/cyclonedds_local_only.xml`; you do
**not** need to set `CYCLONEDDS_URI` manually any more.

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

Four independent layers protect the swarm:

- **Leader-pose watchdog** (`swarm_server`). If the leader's pose goes stale —
  the leader Jetson's view of the leader pose ages past
  `leader_pose_timeout_s` (default 1.5 s) — followers **freeze on the last
  good leader reference** (hold position) instead of chasing a stale
  setpoint, and `/swarm/status` raises the emergency. On the radio link,
  this watchdog ages out *the leader-side `radio_bridge`'s synthesised
  pose for the leader itself* (drone_0's real MAVROS, not synthesised) and
  the synthesised follower poses identically. Exercise it without a real
  dropout: `ros2 param set /swarm_server simulate_leader_dropout true`
  (then `false`).
- **Radio-link watchdog** (`radio_bridge`, follower role). If a follower
  loses leader frames for `radio_loss_brake_s` (default 2.0 s), the
  follower commands its FC into **BRAKE** locally. After
  `radio_loss_disarm_s` (default 10.0 s) without a frame, the follower
  **disarms** itself. The follower does not wait for the leader to notice
  — it brings the airframe to safety on its own.
- **ArduPilot GCS failsafe** (`FS_GCS_ENABLE 1`). If a follower's FC loses
  the MAVLink heartbeat from MAVROS on its own Jetson, the FC triggers RTL.
  (Now intra-Jetson only, not inter-Jetson.)
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
| `swarm_server` sees only some drones | Radio link — on the leader, check `ros2 topic echo /radio/link_age_s`. A finite age means at least one peer is alive; `-1.0` means no peer is reachable. Confirm follower's `radio_bridge` is running (`docker logs orynth-demo-<N>`) and the RFD900s are in the same `NETID` (see `radio_link_bringup.md`). |
| `/swarm/follow_leader` rejected "no pose yet" | The leader is not airborne / not publishing pose — take off first. |
| Followers do not track the leader | Either the leader-pose watchdog has fired (check `/swarm/status` emergency) or the radio link is stale (check `/radio/link_age_s`). |
| `/radio/link_age_s = -1` | No frames from any peer yet. Confirm `radio_bridge` is up on every Jetson, `/dev/ttyUSB_RFD` is present, and radio firmware is configured per `radio_link_bringup.md`. |
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
| Bench link test (no ROS) | `python3 scripts/hardware/fc_link_test.py --port /dev/ttyTHS1 --baud 921600` |
| Props-off motor test | `python3 scripts/hardware/motor_test.py --port /dev/ttyTHS1 --motor 1 --throttle 8` |
| Rehearse leader-follow in SITL | `make leaderfollow-smoke` |
| Leader-follow in Gazebo (on screen) | `make swarm-up` |

---

## 12. See also

- [`first_flight.md`](first_flight.md) — the Phase 2.5b flight procedure.
- [`radio_link_bringup.md`](radio_link_bringup.md) — SiK/RFD900x firmware, wiring, udev, smoke test.
- [`radio_bench_tests.md`](radio_bench_tests.md) — bench chat + props-off motor spin over the radio.
- [`../../scripts/hardware/README.md`](../../scripts/hardware/README.md) — bench link + motor test.
- [`../../config/ardupilot_params/README.md`](../../config/ardupilot_params/README.md) — demo parameters.
- [`sitl_swarm_dev.md`](sitl_swarm_dev.md) — the SITL swarm dev stack.
- [ADR 0008](../adr/0008-leader-follow-demo-integration.md) — leader-follow design.
- [ADR 0009](../adr/0009-mavlink-radio-supersedes-dds-intra-swarm.md) — radio inter-drone transport.
- `COMMANDS.md` — the full reproducible command reference.
