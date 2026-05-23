# Radio link bring-up — SiK / RFD900x for the Orynth swarm

How to wire up, firmware-configure, and smoke-test the SiK / RFD900x telemetry
radios that carry inter-drone traffic in Phase 2.5b (ADR 0009).

> **Scope.** Hardware setup of the radio link itself. The day-to-day swarm
> operations and the command surface that *uses* this link are in
> [`jetson_swarm_operations.md`](jetson_swarm_operations.md). The flight
> procedure is [`first_flight.md`](first_flight.md). The dialect spec is
> [`../../external/mavlink_dialects/orynth_swarm.xml`](../../external/mavlink_dialects/orynth_swarm.xml).

---

## 1. Hardware

| Item | Per Jetson | Notes |
|------|-----------|-------|
| RFD900x or RFD900ux radio | 1 | x = synchronous multipoint; ux = adds 5G modem option board. Either works. |
| Antenna | 1 | RP-SMA dipole; upgrade to a directional / dual-pol on the GCS node for range. |
| USB-to-UART adapter | 1 | If your radio breakout is FTDI-USB (most RFD900x kits are), no adapter is needed. |
| 30 cm USB cable | 1 | Strain-relieve it on the airframe. |

## 2. Wiring

The radio is on the **Jetson**, not the flight controller. Connect:

```
Jetson  USB-A  ── 30 cm cable ──  RFD900x USB
```

There is no UART wiring to the FC. The FC keeps its own MAVLink telemetry
(TELEM1 → ground station laptop on a separate radio, optional) independent of
this inter-drone link. ADR 0009 §2 records why.

## 3. udev rule

To get a stable device path that does not move when other USB-UARTs come and
go, install the udev rule shipped in the repo:

```sh
sudo cp config/udev/99-orynth-rfd900.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger
ls -l /dev/ttyUSB_RFD                    # symlink should now exist
```

If `/dev/ttyUSB_RFD` is missing after this, the FTDI vendor/product id in the
rule may not match your radio variant. Find the real one with `lsusb` and
adjust the `ATTRS{idVendor}` / `ATTRS{idProduct}` fields in the rule file.

## 4. Firmware configuration (SiK / RFD900x multipoint)

Run this **once per radio**, on a laptop or directly on the Jetson it will
live on. The example assumes the RFDesign Tools (`rfdtools`) are installed;
substitute Mission Planner's "SiK Radio" tab if you prefer a GUI.

```sh
# 1. Connect to the radio.
python3 -m rfdtools.cli connect --port /dev/ttyUSB_RFD --baud 57600

# 2. Set the parameters that must match across the swarm.
ATS NETID=42           # network id — every radio in the swarm uses the same
ATS MIN_FREQ=915000    # adjust per region (915 MHz US, 868 MHz EU)
ATS MAX_FREQ=928000
ATS AIR_SPEED=64       # 64 kbps — defaults of demo; can raise to 200 at short range
ATS MAVLINK=1          # SiK framing aligned to MAVLink packets
ATS ECC=1              # forward error correction
ATS DUTY_CYCLE=100     # legal in unlicensed bands at typical RFD900 power

# 3. Distinct NODEID per radio.
#    drone_0 (leader) -> NODEID=0  +  NODECOUNT = total drones (e.g. 2)  +  BASE=1
#    drone_K          -> NODEID=K  +  NODECOUNT = total drones           +  BASE=0
ATS NODEID=0
ATS NODECOUNT=2
ATS BASE=1             # 1 ONLY on the leader's radio

# 4. Write to non-volatile memory, reboot the radio.
AT&W
ATZ
```

After the radio reboots, verify the params:

```sh
python3 -m rfdtools.cli connect --port /dev/ttyUSB_RFD --baud 57600
ATI5                   # dumps all params; spot-check NETID, NODEID, BASE
```

Air-rate options at a glance:

| `AIR_SPEED` | Air rate | Approx. usable | Typical range |
|-------------|----------|---------------|---------------|
| 64          | 64 kbps  | ~38 kbps      | ~3 km dipole-to-dipole |
| 125         | 125 kbps | ~70 kbps      | ~1.5 km |
| 200         | 200 kbps | ~110 kbps     | ~800 m |

Phase 2.5b ships ~6.4 kbps for two drones at 10 Hz state-rate. 64 kbps is the
right default; raise only if you also raise `state_rate_hz` or add more
drones.

## 5. Smoke test (no FC needed)

Bench-test the link before the airframes are even on the table.

### 5.1 Loopback unit test (any host)

```sh
cd ros2_ws
colcon build --packages-select swarm_radio
source install/setup.bash
pytest --rootdir=src/swarm_radio src/swarm_radio/test -q
```

This exercises encode/decode round-trip, partial-frame resync, and watchdog
timing — no hardware involved.

### 5.2 Two-radio chat + props-off motor spin

Two structured bench tests, in order — radio link only, then full
computer → radio → Jetson → FC → motor chain:

[`radio_bench_tests.md`](radio_bench_tests.md)

Run those before bringing the full ROS stack up. They are the cheapest
sanity check that catches the highest-yield failure modes (wrong NETID,
missing udev rule, FC UART wiring).

### 5.3 Full bridge bring-up on two Jetsons

With both radios configured and both Jetsons set up per
`jetson_swarm_operations.md` § 2:

```sh
# Jetson A — leader
DRONE_ID=0 WITH_SWARM_SERVER=1 DRONE_COUNT=2 make demo-up

# Jetson B — follower
DRONE_ID=1 DRONE_COUNT=2 make demo-up
```

On the leader, after both are healthy:

```sh
docker exec -it orynth-demo-0 bash -lc \
  'source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash; \
   ros2 topic echo /radio/link_age_s --once'
```

Expected output: a small positive number (≤ 1.0). `-1.0` means no peer
reached yet — see § 6.

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `/dev/ttyUSB_RFD` missing | udev rule's VID/PID does not match this radio variant; see § 3. |
| `/radio/link_age_s = -1` | Peer never sent a frame. Check `NETID` matches on both radios (`ATI5`). Distance / antennas matter — bench-test at <1 m first. |
| Frames arrive but watchdog still fires | Air-rate too high for range — lower `AIR_SPEED`, or check `ECC=1`. |
| CRC errors flood the receiver | Antenna missing or detuned, or RF interference. Replace the antenna; move away from 2.4 GHz WiFi APs. |
| Setpoints reach the follower but it does not move | `radio_bridge` republished onto `/drone_K/mavros/setpoint_raw/local` but MAVROS rejected: drone not in GUIDED, not armed, or pre-arm-check failed. Confirm with `ros2 topic echo /drone_K/mavros/state`. |
| Setpoints lag by seconds | Bandwidth saturated. With Phase 2.5b's 6.4 kbps budget this shouldn't happen on 64 kbps air-rate — investigate stray subscribers writing to `setpoint_raw/local` at higher than 10 Hz. |

## 7. See also

- [ADR 0009](../adr/0009-mavlink-radio-supersedes-dds-intra-swarm.md) — design rationale and message contract.
- [`../../external/mavlink_dialects/orynth_swarm.xml`](../../external/mavlink_dialects/orynth_swarm.xml) — dialect spec.
- [`../../ros2_ws/src/swarm_radio/swarm_radio/radio_link.py`](../../ros2_ws/src/swarm_radio/swarm_radio/radio_link.py) — wire format implementation.
- RFD900x datasheet — <https://files.rfdesign.com.au/Files/documents/RFD900x%20DataSheet.pdf>
- SiK firmware notes — <https://ardupilot.org/copter/docs/common-3dr-radio-advanced-configuration-and-technical-information.html>
