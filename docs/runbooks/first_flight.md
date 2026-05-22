# First flight — Phase 2.5b leader-follow hardware demo

The first time Orynth v2 flies on **real airframes**. An operator's leader is
flown by a safety pilot; two-to-four follower drones autonomously hold a diamond
relative to the leader's live pose and track it as it moves (`PLAN.md` § D,
Phase 2.5b; ADR 0008).

This flight pulls a hardware demo *ahead* of the full Hardware-in-the-Loop phase
(Phase 6), so the condensed safety gate below is a **hard prerequisite** — no
motor spins on a formation flight until every item is signed off.

> Setup, wiring, and the day-to-day command surface live in
> [`jetson_swarm_operations.md`](jetson_swarm_operations.md). This runbook is the
> *flight* procedure: gate, roles, sequence, aborts, sign-off.

---

## 1. Roles

| Role | Count | Responsibility |
|------|-------|----------------|
| Flight director | 1 | Calls the sequence, owns the go/no-go, calls aborts. |
| Safety pilot | **1 per drone** | Holds that drone's RC transmitter, override armed; flies the leader; can take any follower at any instant. |
| Swarm operator | 1 | Drives the `swarm_server` services from the leader's Jetson / GCS laptop. |

Minimum to fly: flight director + 1 safety pilot per airframe flown (leader + ≥2
followers = 3 airframes = 3 safety pilots). The swarm operator may double as the
flight director only if ≥3 followers each have a dedicated safety pilot.

---

## 2. Condensed safety gate — clear ALL before any motor spins

A subset of the Phase 6 HIL checklist, mandatory because this flight precedes
Phase 6 (`PLAN.md` § D, Phase 2.5b prerequisite).

- [ ] **Phase 2.5a passed in SITL** — `make leaderfollow-smoke` green on this
      build (leader-follow + watchdog proven in the simulator first).
- [ ] **Per-airframe calibration** — compass and accelerometer calibrated on
      *every* drone; ESC calibration done; `FRAME_CLASS` / `FRAME_TYPE` set.
- [ ] **Demo parameters loaded** — `config/ardupilot_params/demo_common.parm` +
      the matching `drone_<N>.parm` on each airframe; FC rebooted
      (see `config/ardupilot_params/README.md`).
- [ ] **Distinct system ids** — each FC reports `SYSID_THISMAV = N + 1`; confirm
      with `scripts/hardware/fc_link_test.py` per drone.
- [ ] **Props-off motor check** — `scripts/hardware/motor_test.py` spins each
      motor; mapping and direction confirmed. Props refitted and checked after.
- [ ] **Props-off GUIDED arm test** — each drone, props **off**: arm in GUIDED
      via the companion, confirm `/drone_<N>/mavros/state` shows `armed: true`,
      disarm. No drone proceeds that cannot arm cleanly.
- [ ] **Geofence + failsafes verified via QGC** — fence enabled; trip RC-loss
      failsafe (transmitter off) and confirm RTL; confirm battery failsafe
      thresholds match the packs.
- [ ] **Single-drone manual hover** — the leader, then *each* follower
      individually, hovers under its safety pilot on RC (LOITER/POSHOLD) and
      lands cleanly. No formation flight until every airframe has hovered solo.
- [ ] **Batteries >90%**, props secure, airframe IDs physically labelled.

Flight director signs the gate (§ 8) before bringup.

---

## 3. Site and conditions

- Open area, clear of people and obstacles; visual line of sight to every drone.
- Wind ≤ ~6 m/s; no precipitation; GPS open sky (HDOP good on all drones).
- **Formation spacing ≥ 5 m** between adjacent slots — the demo flies the
  diamond at `spacing_m: 6.0` so no two drones are closer than 6 m.
- Geofence (`FENCE_RADIUS 50`, `FENCE_ALT_MAX 30`) sized to fit the swarm at
  full spacing with margin; arming point inside it.
- Leader flies low and slow (≤ 3 m/s) — tracking latency over WiFi is
  non-critical at low speed (`PLAN.md` § G).

---

## 4. Bringup

Per-Jetson setup and the DDS LAN are covered in
[`jetson_swarm_operations.md`](jetson_swarm_operations.md) § 5. Summary:

1. **Leader Jetson (drone_0)** — `bash scripts/bringup/demo_swarm.sh up 0`
   (brings up MAVROS + Foxglove + `swarm_server`).
2. **Each follower Jetson** — `bash scripts/bringup/demo_swarm.sh up <N>`.
3. **Preflight gate** — on the leader Jetson: `bash scripts/bringup/demo_swarm.sh
   preflight`. It blocks until the leader and every follower report a live FC
   link, an EKF global origin, and battery > 90%, then prints `PREFLIGHT PASS`.
4. Connect Foxglove Studio to `ws://<leader-jetson-ip>:8765`, load
   `ros2_ws/src/swarm_bringup/config/demo.json`.
5. Each safety pilot powers their transmitter, confirms RC override and a clean
   mode switch to LOITER on their drone.

Do not proceed past a failed preflight.

---

## 5. Flight sequence

The leader is **RC-flown** throughout. The followers are autonomous. The swarm
operator runs the service calls from the leader Jetson; the flight director
calls each step.

1. **Followers + leader to hover.** Operator: `/swarm/takeoff` to 5 m. All
   drones lift in GUIDED and hover.

   ```sh
   ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff '{altitude_m: 5.0}'
   ```

2. **Leader to manual.** The leader's safety pilot switches the leader to
   **LOITER**. The leader is now RC-flown; the companion no longer commands it.
   *RC mode authority is what removes the leader from autonomous control —
   verify the leader holds on the sticks before continuing.*

3. **Engage leader-follow.** Operator: `/swarm/follow_leader` enable, diamond,
   6 m spacing. The four followers form up around the leader's live pose.

   ```sh
   ros2 service call /swarm/follow_leader swarm_msgs/srv/FollowLeader \
     '{enable: true, formation_name: diamond, spacing_m: 6.0}'
   ```

4. **Fly the leader.** The leader pilot flies a slow, gentle path (≤ 3 m/s).
   Watch the live per-follower error on Foxglove `demo.json` — followers should
   hold < 2 m. Track the leader for **≥ 60 s of leader motion**.

5. **Watchdog demonstration.** Operator forces a leader-pose dropout; the
   followers must hold position and `/swarm/status` must raise the emergency.

   ```sh
   ros2 param set /swarm_server simulate_leader_dropout true   # hold ~10 s
   ros2 param set /swarm_server simulate_leader_dropout false
   ```

6. **Disengage.** Operator: `/swarm/follow_leader` disable. Followers stop
   tracking and hold.

   ```sh
   ros2 service call /swarm/follow_leader swarm_msgs/srv/FollowLeader '{enable: false}'
   ```

7. **Land.** The leader pilot lands the leader on RC. Operator lands the
   followers: `/swarm/land`. Confirm every drone disarms.

   ```sh
   ros2 service call /swarm/land std_srvs/srv/Trigger '{}'
   ```

Record the flight: `LEADERFOLLOW_RECORD`-style bag on the leader Jetson plus
flight video → `accept/demo_leaderfollow.mcap`.

---

## 6. Abort triggers and procedures

Any role may call an abort. **Abort is loud and unambiguous.**

| Trigger | Action |
|---------|--------|
| Any drone behaves unexpectedly / drifts toward another | That safety pilot takes RC, flies clear; operator `/swarm/land`. |
| Two drones close below the 5 m floor | Flight director calls abort; **all** safety pilots take RC; land all. |
| Leader-pose watchdog fires unintentionally (`/swarm/status` emergency) | Followers hold automatically; operator disengages `/swarm/follow_leader`; assess link before re-engaging. |
| WiFi / DDS link lost to a follower | That follower's GCS failsafe (`FS_GCS_ENABLE`) triggers RTL; its safety pilot stands ready on RC. |
| Geofence breach | FC auto-RTL (`FENCE_ACTION 1`); safety pilot monitors, takes RC if needed. |
| Low battery on any drone | That FC auto-RTL; land the rest in good order. |
| Any doubt | Land. The demo is not worth an incident. |

**Universal abort:** every safety pilot switches their drone to LOITER/LAND on
RC and lands it. RC override always wins — it is the last line of defence.

---

## 7. Acceptance criteria

From `PLAN.md` § D, Phase 2.5b:

- [ ] Outdoors, open area, formation spacing ≥ 5 m.
- [ ] Leader manually piloted (LOITER/POSHOLD) by a safety pilot.
- [ ] ≥ 2 followers (target 4) autonomously take off, form up, and track the
      manually-moved leader for **≥ 60 s of leader motion**.
- [ ] Mean horizontal formation error **< 2 m per follower** (looser than the
      0.5 m SITL gate — hardware GPS without RTK, wind, first flight).
- [ ] The leader-pose watchdog demonstrably holds a follower on a simulated
      link drop.
- [ ] Coordinated land; every drone disarms.
- [ ] Recorded as `accept/demo_leaderfollow.mcap` + flight video.

No CI gate — this is a hardware flight.

---

## 8. Sign-off

| Item | Name | Signature | Date |
|------|------|-----------|------|
| Condensed safety gate (§ 2) cleared | | | |
| Flight director | | | |
| Safety pilot — drone_0 (leader) | | | |
| Safety pilot — drone_1 | | | |
| Safety pilot — drone_2 | | | |
| Safety pilot — drone_3 | | | |
| Safety pilot — drone_4 | | | |
| Acceptance criteria (§ 7) met | | | |
| Maintainer | | | |

Demo footage and `accept/demo_leaderfollow.mcap` attached to the Phase 2.5b
milestone.
