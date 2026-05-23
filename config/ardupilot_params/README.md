# ArduPilot demo parameters — Phase 2.5b

Per-airframe ArduPilot Copter parameters for the leader-follow hardware demo
(`PLAN.md` § D, Phase 2.5b). They put every airframe into a known, conservative
state — tight geofence, all failsafes armed, modest GUIDED speeds — and give
each drone a **distinct MAVLink system id** so the five MAVROS instances on the
Cyclone DDS LAN never collide.

| File | Load on | Sets |
|------|---------|------|
| `demo_common.parm` | every drone | geofence, RC/GCS/battery failsafes, GUIDED tuning, companion telemetry streams |
| `drone_0.parm` | leader  | `SYSID_THISMAV 1` |
| `drone_1.parm` | follower | `SYSID_THISMAV 2` |
| `drone_2.parm` | follower | `SYSID_THISMAV 3` |
| `drone_3.parm` | follower | `SYSID_THISMAV 4` |
| `drone_4.parm` | follower | `SYSID_THISMAV 5` |

`SYSID_THISMAV = DRONE_ID + 1`. It must match the MAVROS `tgt_system`
(`DRONE_ID + 1`, set by `hw_drone.launch.py`) — a shared id silently kills one
MAVROS router. This is the same per-instance SYSID rule the SITL swarm uses
(`PLAN.md` § G).

## Loading them

Load `demo_common.parm` first, then the one `drone_<N>.parm` for that airframe.
Any of these works:

**Mission Planner** (primary) — *Config → Full Parameter List → Load from file*,
pick `demo_common.parm`, click **Write Params**; repeat for `drone_<N>.parm`,
then **reboot the FC**. (Mission Planner loads into the grid first — the
**Write Params** step is what actually pushes them to the FC.)

**QGroundControl** — *Vehicle Setup → Parameters → Tools → Load from file*,
pick `demo_common.parm`, repeat for `drone_<N>.parm`, then **reboot the FC**.

**MAVProxy / pymavlink** (over the same serial link `fc_link_test.py` uses):

```sh
mavproxy.py --master=/dev/ttyTHS1 --baudrate=921600
param load config/ardupilot_params/demo_common.parm
param load config/ardupilot_params/drone_0.parm     # match the airframe
param fetch                                          # verify
```

Then reboot the flight controller so geofence and failsafe params take effect.

## Before they are correct for your hardware

These are a **starting point**. Review at least:

- **`BATT_LOW_VOLT` / `BATT_CRT_VOLT`** — set for your actual pack chemistry
  and cell count. The defaults assume a 4S pack.
- **`SERIAL1_*` / `SR1_*`** — `demo_common.parm` assumes the Jetson is wired to
  **TELEM1 = SERIAL1**. Pixhawk-class boards expose a labeled `TELEM1` JST-GH
  connector that maps to `SERIAL1`. **F4-class boards (e.g. Matek F405) expose
  TX/RX solder pads** — which pad pair corresponds to which `SERIALn` is fixed
  by that board's hwdef (see the Matek datasheet for your specific variant).
  If the companion is on another port, set the matching `SERIALn_PROTOCOL 2`,
  `SERIALn_BAUD`, and `SRn_*` stream rates instead, and point `FCU_URL` at the
  right baud. MAVROS does not request data streams, so without the `SRn_*`
  rates `/drone_<N>/mavros/local_position/pose` stays silent.
- **F4-class boards (Matek F405 and similar)** — confirm the firmware target
  supports Copter (`MatekF405` / `MatekF405-CTR` do; `MatekF405-Wing`,
  `MatekF405-SE`, `MatekF405-WSE` are Plane/VTOL targets and will not fly
  multicopter). These boards have **no hardware safety switch** — set
  `BRD_SAFETY_DEFLT 0` so arming is not gated on a switch that does not exist.
  F4 flash limits mean some ArduPilot features (AP_DDS, scripting, ADSB, extra
  EKF lanes) are not built into the firmware — v2.0.0 only requires MAVLink,
  which is always present, but the long-term ADR-0002 swap to AP_DDS is **not
  available** on these boards.
- **`FENCE_RADIUS` / `FENCE_ALT_MAX`** — size to your actual flight area; the
  swarm must fit inside the fence at full formation spacing.
- **Airframe tune** — `FRAME_CLASS` / `FRAME_TYPE`, compass and accel
  calibration, ESC calibration, and a real PID tune are airframe-specific and
  are **not** in these files. They are part of the Phase 2.5b safety gate
  (`docs/runbooks/first_flight.md`).

Verify the link and identity afterwards with
`python3 scripts/hardware/fc_link_test.py --port /dev/ttyTHS1 --baud 921600` —
it prints the system id the FC reports.
