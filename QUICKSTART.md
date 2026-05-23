# Jetson Quickstart — get the swarm flying

Minimal path from a fresh Jetson to a follower drone tracking a leader on RC.
Two drones (leader + 1 follower). Once this works, scale to five.

**Skip for now:** `PLAN.md`, `WALKTHROUGH.md`, `COMMANDS.md`, `sitl_swarm_dev.md`,
all the ADRs. They are useful, just not on the critical path.

**Deep dives this doc points at, in order:**
1. [`docs/runbooks/jetson_swarm_operations.md`](docs/runbooks/jetson_swarm_operations.md) — full per-Jetson setup and command surface.
2. [`scripts/hardware/README.md`](scripts/hardware/README.md) — bench link test if a Jetson can't see its FC.
3. [`config/ardupilot_params/README.md`](config/ardupilot_params/README.md) — loading FC params.
4. [`docs/runbooks/intermediary_tests.md`](docs/runbooks/intermediary_tests.md) — the 1- and 2-drone acceptance tests.
5. [`docs/runbooks/first_flight.md`](docs/runbooks/first_flight.md) — flight safety gate and procedure (read before you spin a motor).

---

## 0. Hardware prerequisites (once, before any Jetson work)

- WiFi access point on the field. Jetsons get static IPs `192.168.42.10..14`
  (`.10` = drone_0, ..., `.14` = drone_4); GCS laptop on `192.168.42.1`.
- Each Jetson: 5 V / 5 A+ BEC straight off the battery (**not** the FC power
  module — Orin Nano peaks ~25 W).
- Each Jetson: NVMe SSD boot (microSD will die fast under rosbag + Docker).
- Chrony / PTP across the LAN so all clocks are within 10 ms. A drifting clock
  causes false leader-pose watchdog trips.

---

## 1. Per-Jetson one-time setup

Do this **on every Jetson you intend to fly**. `$N` = that drone's id (0..4).

### 1.1 Confirm the board

```sh
cat /etc/nv_tegra_release   # expect R36 (JetPack 6 / L4T r36)
```

R32 (original Nano) won't work with the current base image. Stop here if so.

### 1.2 Clone

```sh
git clone https://github.com/Nikola-code-ai/orynth-v2.git ~/orynth-v2
cd ~/orynth-v2/v2
```

### 1.3 Free the serial port + wire it to the FC

```sh
sudo systemctl stop nvgetty && sudo systemctl disable nvgetty
sudo usermod -aG dialout "$USER"   # re-login after this
sudo lsof /dev/ttyTHS1             # expect no output
```

Wire **Jetson UART ↔ FC TELEM1** (or the FC pads mapped to `SERIAL1`): TX↔RX
crossed, GND common, **no +5 V to the Jetson**. Three wires only.

### 1.4 Load the ArduPilot demo params

On each FC, via Mission Planner / QGC / MAVProxy:

1. Load `config/ardupilot_params/demo_common.parm` — Write Params.
2. Load the matching `config/ardupilot_params/drone_$N.parm` — Write Params.
3. Reboot the FC.

Verify the link:

```sh
python3 scripts/hardware/fc_link_test.py --port /dev/ttyTHS1 --baud 921600
```

If this fails, fix it here before continuing. Don't go to step 1.5 with a
broken link. See `scripts/hardware/README.md` for wiring + troubleshooting.

### 1.5 Static IP + DDS peer list

Set this Jetson's WiFi to `192.168.42.1$N` (e.g. drone_0 = `.10`, drone_1 = `.11`).
Then make the per-Jetson DDS config:

```sh
cp config/networks/cyclonedds_drone_template.xml \
   config/networks/cyclonedds_drone_$N.xml
```

Edit `cyclonedds_drone_$N.xml`:
- `<NetworkInterfaceAddress>` → your WiFi iface (usually `wlan0`).
- `<Peers>` → IP of every drone you plan to fly + the GCS. The template is
  pre-populated for `.10`–`.14` + `.1`; adjust if your subnet differs.

### 1.6 Build the base image

Native arm64 build, slow the first time (~30–60 min):

```sh
make base
```

---

## 2. Bring up — single drone first

On the leader Jetson (`drone_0`), prove one drone end-to-end:

```sh
cd ~/orynth-v2/v2
export DRONE_COUNT=1
export CYCLONEDDS_URI=file:///workspace/config/networks/cyclonedds_drone_0.xml
bash scripts/bringup/demo_swarm.sh up 0
```

`up 0` brings up MAVROS + Foxglove + `swarm_server` and blocks until the
MAVROS↔FC link is live.

Preflight gate (still on the leader):

```sh
export DRONE_COUNT=1
bash scripts/bringup/demo_swarm.sh preflight
```

It checks live FC link + EKF global origin + battery > 90%, then prints
`PREFLIGHT PASS`.

Sanity check from the operator laptop: open Foxglove Studio, connect to
`ws://192.168.42.10:8765`, import `ros2_ws/src/swarm_bringup/config/demo.json`.
You should see `drone_0` pose.

**Optional, props off, safety pilot ready:** test the takeoff/land service
surface — see `intermediary_tests.md` § 1.

Tear down before moving on:

```sh
bash scripts/bringup/demo_swarm.sh down 0
```

---

## 3. Bring up — leader + 1 follower

This is the goal: you fly the leader on RC, the follower tracks it.

**On the leader Jetson (`drone_0`):**

```sh
cd ~/orynth-v2/v2
export DRONE_COUNT=2
export CYCLONEDDS_URI=file:///workspace/config/networks/cyclonedds_drone_0.xml
bash scripts/bringup/demo_swarm.sh up 0
```

**On the follower Jetson (`drone_1`):**

```sh
cd ~/orynth-v2/v2
export DRONE_COUNT=2
export CYCLONEDDS_URI=file:///workspace/config/networks/cyclonedds_drone_1.xml
bash scripts/bringup/demo_swarm.sh up 1
```

**Preflight gate (leader Jetson):**

```sh
export DRONE_COUNT=2
bash scripts/bringup/demo_swarm.sh preflight
```

Wait for `PREFLIGHT PASS` for both drones.

---

## 4. Fly it

Convenience shell for service calls (on the leader Jetson):

```sh
swarm() { docker exec -it orynth-demo-0 bash -lc \
  "source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash; ros2 $*"; }
```

Safety pilots ready, geofence verified, **then**:

```sh
# Coordinated takeoff
swarm service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff '{altitude_m: 5.0}'
```

Safety pilot on `drone_0` switches the leader to `LOITER` and takes manual RC.

```sh
# Engage live leader-follow — 6 m diamond, heading-locked
swarm service call /swarm/follow_leader swarm_msgs/srv/FollowLeader \
  '{enable: true, formation_name: diamond, spacing_m: 6.0}'
```

The follower now tracks the leader's live pose. Fly the leader slow and low
(≤ 3 m/s) — over WiFi, tracking latency degrades fast above that.

**To stop:**

```sh
swarm service call /swarm/follow_leader swarm_msgs/srv/FollowLeader '{enable: false}'
swarm service call /swarm/land std_srvs/srv/Trigger '{}'
```

---

## 5. Teardown

On each Jetson:

```sh
bash scripts/bringup/demo_swarm.sh down $N
```

---

## 6. If it breaks

| Symptom | Where to look |
|---|---|
| `up` healthcheck times out | TX/RX swap, baud, console getty, or unpowered FC. Run `fc_link_test.py`. |
| `preflight` hangs on a drone | No link / no EKF origin / battery ≤ 90%. The output names which. |
| Drones can't see each other | DDS peers — check every IP listed in `cyclonedds_drone_$N.xml`, `wlan0` is the right iface, all on `ROS_DOMAIN_ID=42`. |
| `follow_leader` rejected "no pose yet" | Leader not airborne / not publishing pose. Take off first. |
| Follower doesn't move | Leader pose stale — `/swarm/status` will show the watchdog. Check WiFi to leader. |
| MAVROS instances colliding | Duplicate `SYSID_THISMAV`. Each FC must report `N + 1`. |

Full troubleshooting table: `jetson_swarm_operations.md` § 10.

---

## 7. Once two drones work

Scaling to the full swarm = repeat § 1 on `drone_2..4`, then bring each up
with `demo_swarm.sh up $N` and drop the `DRONE_COUNT` override (defaults to 5).
Read `first_flight.md` end-to-end before flying any new formation count for
the first time.
