# Radio bench tests — link smoke + props-off motor spin

Two minimal bench tests for the SiK / RFD900x inter-drone link (ADR 0009):

1. **Test 1 — Radio chat.** Computer ↔ Jetson over the radio. No FC. No
   airframe. Prove the link carries Orynth frames cleanly before you go
   anywhere near a flight controller.
2. **Test 2 — Motor low-RPM via radio.** Computer sends a motor-test
   command over the radio; the Jetson relays it to its FC over UART; one
   motor spins briefly at low throttle. **Props off, airframe restrained.**

Run them in order. Test 2 is invalid if Test 1 is not clean.

> Prerequisites for both tests:
> - Two SiK/RFD900x radios paired per
>   [`radio_link_bringup.md`](radio_link_bringup.md) (matching `NETID`,
>   distinct `NODEID`).
> - On the Jetson, the udev rule installed so `/dev/ttyUSB_RFD` exists.
> - `pip install pymavlink pyserial` on both ends (or use the Orynth
>   container on the Jetson — `pyserial` is already in `orynth-base`).
> - No ROS/colcon required for these bench scripts; they import
>   `swarm_radio.radio_link` from the repo directly.

---

## Test 1 — Radio chat (no FC)

### Hardware

| End | Hardware | Serial device |
|-----|----------|---------------|
| Computer (laptop / desktop) | One paired radio on USB | Linux: `/dev/ttyUSB0` · macOS: `/dev/tty.usbserial-XXXX` · Windows (WSL2): pass-through to `/dev/ttyUSB0` |
| Jetson | The drone-side radio on USB | `/dev/ttyUSB_RFD` (via the udev rule) |

Antennas screwed on, both ends powered, radios within sight on a bench.

### Run

**Terminal A — Computer:**

```sh
cd ~/Projects/Orynth/v2
python3 scripts/hardware/radio_chat.py \
    --device /dev/ttyUSB0 \
    --drone-id 100 \
    --peer-id 1
```

**Terminal B — Jetson** (over SSH or on the device):

```sh
cd ~/orynth-v2/v2
python3 scripts/hardware/radio_chat.py \
    --device /dev/ttyUSB_RFD \
    --drone-id 1 \
    --peer-id 100
```

Pick any unused logical id on each side — `100` on the computer (GCS-like)
and `1` on the Jetson (the drone) is the convention used throughout this
runbook. The script tags every send with that id and prints every receive.

### Pass criteria

Within a couple of seconds, each side prints lines like:

```
  RX Heartbeat   from drone_1 role=0 uptime=3s
  RX DroneState  from drone_1 pos=(+0.98,+0.20,+2.00) mode=BENCH
  [status] link age (drone_1) = 0.05s
```

Pass if **both** of these hold for ≥ 30 s on **both** sides:

- The `RX ...` lines arrive continuously (DroneState ≥ once per second,
  Heartbeat ≥ twice per second).
- `[status] link age` stays **< 0.6 s** on both ends.

Stop with `Ctrl-C` on each terminal.

### Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `FAILED to open /dev/ttyUSB_RFD: [Errno 2] No such file or directory` | udev rule not installed or radio VID/PID mismatch. See `radio_link_bringup.md` § 3. |
| `Permission denied` opening the serial device | Add yourself to the `dialout` group (`sudo usermod -aG dialout $USER`, log out + back in), or run with `sudo`. |
| One side never prints `RX ...` | `NETID` mismatch on the radios — by far the most common cause. Re-check with `ATI5` on both radios. |
| Frames arrive but `link age` keeps growing | Lots of CRC errors → bad antenna, bad cable, or RF interference. Move away from 2.4 GHz WiFi APs; tighten antenna connectors. |
| `link age` flickers between low and high | Loose antenna or USB connector — wiggle-test, re-seat. |

---

## Test 2 — Motor low-RPM via radio (props off!)

This proves the full chain: **computer → radio → Jetson → MAVLink/UART → FC → motor.**

> **⚠ Safety**
> - **PROPS OFF every motor.** Verify physically before powering the ESCs.
> - **Airframe restrained** — bench-vice or zip-tied to a heavy plate. A
>   loose airframe with one motor running will fling itself.
> - **Battery safety switch within reach.** Default plan is to kill power
>   if anything looks wrong.
> - One person on the safety switch, one person on the computer.
> - Throttle stays ≤ 15 % (hard-capped at 30 % in code). Duration ≤ 10 s.

### Hardware

| End | Hardware | Serial device |
|-----|----------|---------------|
| Computer | Paired radio | `/dev/ttyUSB0` (or your platform's equivalent) |
| Jetson | Paired radio | `/dev/ttyUSB_RFD` |
| Jetson | UART to flight controller | `/dev/ttyTHS1` @ 921600 baud (per `demo_common.parm`) |
| Airframe | Powered FC, ESCs, **one motor wired to motor-1 output** | — |

ESCs must be powered (battery connected). Vehicle disarmed (it should be —
ArduPilot boots disarmed). Geofence inactive on the bench is fine.

### Step 1 — start the responder on the Jetson

Over SSH on the Jetson:

```sh
cd ~/orynth-v2/v2
python3 scripts/hardware/radio_motor_responder.py \
    --radio /dev/ttyUSB_RFD \
    --drone-id 1 \
    --fc /dev/ttyTHS1 --fc-baud 921600
```

The responder will:

1. Print a safety banner and **block on a `props are off` confirmation**.
2. Open the FC, confirm a heartbeat and that the vehicle is disarmed.
3. Open the radio.
4. Loop, listening for `ORYNTH_MOTOR_TEST`.

If the FC step fails, **stop and fix it before continuing** — the radio is
not the problem.

### Step 2 — send one motor spin from the computer

On the computer, with `radio_chat` from Test 1 stopped:

```sh
cd ~/Projects/Orynth/v2
python3 scripts/hardware/radio_motor_test.py \
    --device /dev/ttyUSB0 \
    --gcs-id 100 --target-id 1 \
    --motor 1 --throttle 8 --duration 2
```

It will:

1. Print a safety banner and block on the same `props are off` confirmation.
2. Send one `ORYNTH_MOTOR_TEST` frame.
3. Wait up to 5 s for the matching `ORYNTH_ACK`.

### Pass criteria

- The responder log on the Jetson prints:

  ```
    RX MotorTest from drone_? seq=NNNN motor=1 thr=8% dur=2s
    [dispatch] motor=1 throttle=8% duration=2s
    [result]   OK: motor 1 spinning 8% 2s
  ```

- Motor 1 spins at low RPM for ~2 seconds, then stops on its own.
- The computer prints:

  ```
  OK: motor 1 spinning 8% 2s
  ```

  and exits with status 0.

### Step 3 — iterate per motor

Repeat with `--motor 2`, `--motor 3`, … to walk every motor. Stop and
investigate immediately on any unexpected behaviour.

### Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| Responder: `no FC heartbeat. run scripts/hardware/fc_link_test.py to debug.` | FC UART / baud / wiring issue. Use the direct bench test (`scripts/hardware/fc_link_test.py`) to isolate. |
| Responder: `FC reports ARMED. disarm before bench motor tests.` | Vehicle armed (RC stick or unsafe switch). Disarm before continuing. |
| Sender: `FAIL: no ACK received` | Radio link broken or responder not running. Re-run Test 1; check the responder terminal for tracebacks. |
| Sender: `FAIL: remote refused: throttle X% > ceiling Y%` | Sender or responder ceiling lower than requested throttle. Either lower `--throttle` or raise `--max-throttle` deliberately on **both** ends. |
| Responder: `[result] FAIL: FC rejected: …MAV_RESULT_UNSUPPORTED…` | FC's `FRAME_CLASS` / `FRAME_TYPE` not set, or motor index out of range for this frame. Set parameters per `config/ardupilot_params/README.md`. |
| Responder: `[result] FAIL: FC rejected: …MAV_RESULT_DENIED…` | Safety switch still engaged on the FC. Press and hold to acknowledge, then retry. |
| Motor spins but ACK never returns | Bidirectional radio path broken — RX path works (responder got the frame), TX path doesn't. Check both antennas; some radios have separate TX/RX paths. |
| Wrong motor spins | Motor wiring vs ArduPilot motor-index mismatch. Check ArduPilot's motor order for your `FRAME_TYPE` (e.g. X quad: 1=front-right). |

---

## What these tests prove

| Layer | Test 1 | Test 2 |
|-------|--------|--------|
| Radio firmware (NETID, NODEID, MAVLink framing) | ✅ | ✅ |
| `swarm_radio.radio_link` encode / decode / CRC | ✅ | ✅ |
| udev rule on the Jetson | ✅ | ✅ |
| Jetson ↔ FC UART | — | ✅ |
| pymavlink → FC `MAV_CMD_DO_MOTOR_TEST` | — | ✅ |
| Full computer → radio → Jetson → FC chain | — | ✅ |

Anything Test 2 catches that Test 1 didn't is on the **FC side** of the
Jetson, not the radio side. That maps directly to the troubleshooting
table — start with the link, then the responder, then the FC.

## What these tests deliberately do not cover

- ROS 2 / `radio_bridge` integration. That comes next, via
  [`jetson_swarm_operations.md`](jetson_swarm_operations.md) § 5.
- Multipoint (>2 nodes). Both bench tests are 1:1. For 3-node verification,
  start `radio_chat` on every node and confirm each sees the other two.
- Range testing. Bench-distance only — separate runbook when we add field
  range testing.

## See also

- [`radio_link_bringup.md`](radio_link_bringup.md) — radio firmware + udev.
- [`../../scripts/hardware/fc_link_test.py`](../../scripts/hardware/fc_link_test.py) — direct FC UART smoke (no radio).
- [`../../scripts/hardware/motor_test.py`](../../scripts/hardware/motor_test.py) — direct FC motor test (no radio).
- [ADR 0009](../adr/0009-mavlink-radio-supersedes-dds-intra-swarm.md) — radio-link design rationale.
