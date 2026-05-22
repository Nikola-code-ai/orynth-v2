# Hardware FC link bring-up

A small, standalone deliverable for learning and bench testing: connect from
your workstation into the **Jetson Nano**, confirm the **MAVLink** link to the
wired **ArduPilot** flight controller, then (props off) nudge a single motor.

This is intentionally *outside* the ROS 2 / MAVROS stack — pure `pymavlink`,
so there is nothing to build. It is also outside the ADR-0007 pinned/hashed
dependency set on purpose: it is a bench tool that runs on the Jetson, not in
the container image.

| File | Purpose | Safe with props on? |
|------|---------|---------------------|
| `fc_link_test.py` | Heartbeat + telemetry health report | Yes — moves nothing |
| `motor_test.py`   | Spin ONE motor at low throttle      | **No — remove props** |

## Safety

`motor_test.py` spins a real motor. **Remove every propeller first.** ESCs
have a deadband, so a motor that looks dead can jump to a real spin the moment
throttle clears the threshold. Hold the airframe down, keep clear, and keep a
hand on the battery/safety switch. The script requires a typed confirmation,
but it cannot see your bench — removing the props is on you.

## Step 1 — SSH into the Jetson

```sh
# IP from your router, or via mDNS if avahi is running:
ssh <user>@<jetson-ip>        # e.g. ssh orynth@192.168.1.42
# or:  ssh <user>@<hostname>.local
```

## Step 2 — Free and identify the serial port

The 40-pin header UART on the Nano is `/dev/ttyTHS1`. Confirm it exists and is
not held by a serial-console login service:

```sh
ls -l /dev/ttyTHS1                       # device should exist
sudo systemctl stop nvgetty 2>/dev/null  # release it if a console holds it
sudo systemctl disable nvgetty 2>/dev/null
sudo lsof /dev/ttyTHS1                   # expect NO output
```

Add yourself to `dialout` so you can open the port without sudo, then
re-login (or reboot) for it to take effect:

```sh
sudo usermod -aG dialout "$USER"
```

## Step 3 — Check the wiring

Jetson 40-pin header  ->  FC TELEM port. **Cross TX and RX.** Connect only
three wires — never run the TELEM port's +5V into the Jetson:

| Jetson pin | Signal     | FC TELEM |
|------------|------------|----------|
| pin 8      | UART2 TX   | RX       |
| pin 10     | UART2 RX   | TX       |
| pin 6 (GND)| GND        | GND      |

Both sides are 3.3V logic — compatible. If the link is flaky, it is usually
TX/RX swapped, a baud mismatch, or hardware flow control (set the FC's
`BRD_SERn_RTSCTS = 0` for the TELEM port you used).

## Step 4 — Install pymavlink

```sh
python3 -m venv ~/orynth-bench && source ~/orynth-bench/bin/activate
pip install pymavlink
```

## Step 5 — Connection test (props may stay on — nothing moves)

```sh
python3 fc_link_test.py --port /dev/ttyTHS1 --baud 57600
```

`--baud 57600` is the ArduPilot TELEM default (`SERIALx_BAUD`). If you raised
that on the FC (e.g. 921600), pass the matching value. A healthy run prints a
heartbeat, then a battery / GPS / attitude snapshot.

## Step 6 — REMOVE EVERY PROPELLER

Not optional. Do it now, then double-check each motor.

## Step 7 — Motor test (props off)

```sh
python3 motor_test.py --port /dev/ttyTHS1 --motor 1 --throttle 8 --timeout 3
```

- `--motor` is the motor number in ArduPilot's test order (1-indexed) — watch
  which motor actually spins and note the mapping.
- `--throttle` is a percent. Start at ~6–8%; if the motor only buzzes it is
  below the ESC deadband — raise in 2% steps. The script caps at 15%.
- `--timeout` is how long it spins; the FC stops it automatically.

If the FC **rejects** the command: the safety switch is likely still engaged
(press and hold until the LED is solid, or set `BRD_SAFETY_DEFLT 0`), the
frame is not configured (`FRAME_CLASS` / `FRAME_TYPE`), or the ESCs are
unpowered. The vehicle must be disarmed — motor test runs while disarmed.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `Could not open /dev/ttyTHS1` | Not in `dialout`, or a console getty still holds the port |
| No heartbeat | TX/RX swapped, baud mismatch, or FC unpowered |
| Heartbeat OK, motor test rejected | Safety switch on, or frame params unset |
| Motor buzzes but will not turn | Throttle below ESC deadband — raise `--throttle` |

---

# Part 2 — MAVROS (the real v2 stack)

Part 1 proved the physical link with raw `pymavlink`. Part 2 points the
**actual Orynth v2 stack** — MAVROS — at that same serial link, so the
hardware is exercised by the production path (ADR 0002), not a bench script.

It reuses the existing bringup unchanged: `docker/compose.hw.yaml` is
`compose.dev.yaml` with the `sitl` service removed and the host serial device
passed through. `sitl_companion.sh` / `sitl_single.launch.py` are already
`FCU_URL`-driven — the "sitl" in their names is historical, nothing simulates.

## Step A — Confirm the board (do this first)

The arm64 base image is built `FROM nvcr.io/nvidia/l4t-jetpack:r36.3.0` —
**JetPack 6 / L4T r36**, which targets the **Jetson Orin** family. On the
Jetson:

```sh
cat /etc/nv_tegra_release      # expect: # R36 (release), REVISION: 3.x
```

- `R36` → Orin board, the prebuilt base image runs as-is. Proceed.
- `R32` → this is an *original* Jetson Nano (JetPack 4 / Ubuntu 18.04). The
  r36 container will not run on it. Stop and raise it — the base image needs
  an r32-compatible target, or MAVROS must run another way.

## Step B — Prep the host serial port

Same as Part 1, Steps 2–3: the device exists, no console getty holds it, TX/RX
wired correctly. **One owner only** — stop the Part 1 script and any MAVProxy
session before bringing MAVROS up; they cannot share `/dev/ttyTHS1`.

## Step C — Build the base image on the Jetson

The image must be built natively on the Jetson (arm64). First time is slow:

```sh
make base          # builds orynth-base:dev for this board's architecture
```

## Step D — Bring MAVROS up against the FC

```sh
make hw-up                                  # /dev/ttyTHS1 @ 57600 baud
# non-default device or baud:
FC_DEVICE=/dev/ttyUSB0 FCU_URL=serial:///dev/ttyTHS1:921600 make hw-up
```

`make hw-up` runs `docker compose -f docker/compose.hw.yaml up -d --wait`. The
healthcheck only reports healthy once `/mavros/state` shows `connected: true`,
so a successful `--wait` *is* proof the MAVROS↔FC link is live.

## Step E — Verify the link

```sh
make hw-check        # runs scripts/hardware/mavros_link_check.sh in-container
```

This prints `/mavros/state`, battery, IMU and GPS, then asserts
`connected: true` (exit 0 = PASS). For ad-hoc poking:

```sh
docker exec -it orynth-companion bash -c \
  'source /opt/ros/humble/setup.bash && ros2 topic echo /mavros/state'
```

## Step F — Foxglove

The Foxglove bridge is exposed on `ws://<jetson-ip>:8765` — connect Foxglove
Studio to watch the live MAVROS topics.

## Tear down

```sh
make hw-down
```

## Troubleshooting (MAVROS)

| Symptom | Likely cause |
|---------|--------------|
| `up --wait` times out | MAVROS never reached `connected: true` — see `make hw-check` output |
| Container exits / image won't run | L4T mismatch — re-check Step A (`/etc/nv_tegra_release`) |
| `connected: false` | Baud/device wrong in `FCU_URL`, TX/RX swapped, or FC unpowered |
| `could not open ... /dev/ttyTHS1` | Device not in `devices:`, or another process owns the port |
| MAVROS healthy in SITL, not on hardware | `compose.dev.yaml` uses a TCP `FCU_URL`; hardware needs the `serial://` form |
