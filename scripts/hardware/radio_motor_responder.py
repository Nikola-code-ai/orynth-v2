#!/usr/bin/env python3
"""Jetson-side responder for the radio motor bench test (props-off).

Listens on the SiK/RFD900x link for ``ORYNTH_MOTOR_TEST`` frames. On each
frame, opens the local flight controller over UART and issues
``MAV_CMD_DO_MOTOR_TEST`` for the requested motor at the requested low
throttle for the requested duration. Replies over the radio with
``ORYNTH_ACK`` (matching seq) reporting accepted / rejected.

***  DANGER -- THIS SPINS A REAL MOTOR.  ***
***  REMOVE EVERY PROPELLER BEFORE RUNNING THIS SCRIPT.  ***

Hard safety rails (refuses to dispatch if violated):
  * throttle clamped to 30%; default ceiling 15%, raisable via ``--max-throttle``
  * duration clamped to 10 s
  * declines if the FC reports the vehicle armed
  * one motor at a time

Procedure: docs/runbooks/radio_bench_tests.md § Test 2.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "ros2_ws" / "src" / "swarm_radio"))

from swarm_radio.radio_link import (  # noqa: E402
    Ack,
    Heartbeat,
    MotorTest,
    RadioLink,
    SerialTransport,
)

try:
    from pymavlink import mavutil
except ImportError:
    sys.exit("pymavlink is not installed. Run: pip install pymavlink")


SAFE_THROTTLE_CEILING_PCT = 15
HARD_THROTTLE_CAP_PCT = 30
HARD_DURATION_CAP_S = 10


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--radio",
        default=os.environ.get("RADIO_DEVICE", "/dev/ttyUSB_RFD"),
        help="radio serial device (default /dev/ttyUSB_RFD)",
    )
    p.add_argument(
        "--radio-baud",
        type=int,
        default=int(os.environ.get("RADIO_BAUD", "57600")),
        help="radio baud (default 57600)",
    )
    p.add_argument(
        "--drone-id",
        type=int,
        required=True,
        help="this Jetson's logical drone id (matches --target-id on the sender)",
    )
    p.add_argument(
        "--fc",
        default="/dev/ttyTHS1",
        help="flight controller UART device (default /dev/ttyTHS1)",
    )
    p.add_argument(
        "--fc-baud",
        type=int,
        default=921600,
        help="FC UART baud (default 921600 — must match SERIAL2_BAUD)",
    )
    p.add_argument(
        "--max-throttle",
        type=int,
        default=SAFE_THROTTLE_CEILING_PCT,
        help=f"override the {SAFE_THROTTLE_CEILING_PCT}%% safety ceiling (still capped at {HARD_THROTTLE_CAP_PCT}%%)",
    )
    return p.parse_args()


def open_fc(port: str, baud: int):
    print(f"opening FC {port} @ {baud} baud ...")
    master = mavutil.mavlink_connection(port, baud=baud)
    hb = master.wait_heartbeat(timeout=15)
    if hb is None:
        sys.exit("no FC heartbeat. run scripts/hardware/fc_link_test.py to debug.")
    if hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
        sys.exit("FC reports ARMED. disarm before bench motor tests.")
    print(f"FC heartbeat OK (sysid={master.target_system}, disarmed).")
    return master


def dispatch_motor_test(master, motor: int, throttle_pct: int, duration_s: int) -> tuple[bool, str]:
    """Issue MAV_CMD_DO_MOTOR_TEST and wait briefly for COMMAND_ACK."""
    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST,
        0,
        motor,
        mavutil.mavlink.MOTOR_TEST_THROTTLE_PERCENT,
        float(throttle_pct),
        float(duration_s),
        0,
        0,
        0,
    )
    deadline = time.time() + 3.0
    while time.time() < deadline:
        m = master.recv_match(type="COMMAND_ACK", blocking=True, timeout=1.0)
        if m is not None and m.command == mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST:
            if m.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                return True, f"motor {motor} spinning {throttle_pct}% {duration_s}s"
            name = mavutil.mavlink.enums["MAV_RESULT"][m.result].name
            return False, f"FC rejected: {name}"
    return False, "no COMMAND_ACK from FC"


def handle_motor_test(args, link: RadioLink, master, mt: MotorTest) -> None:
    if mt.drone_id != args.drone_id and mt.drone_id != 255:
        return
    motor = max(1, min(8, int(mt.motor_index)))
    throttle = max(0, min(HARD_THROTTLE_CAP_PCT, int(mt.throttle_pct)))
    duration = max(1, min(HARD_DURATION_CAP_S, int(mt.duration_s)))

    if throttle > args.max_throttle:
        msg = f"refused: throttle {throttle}% > ceiling {args.max_throttle}%"
        print(f"  [refuse] {msg}")
        link.send_ack(
            Ack(
                time_boot_ms=link.boot_ms(),
                drone_id=args.drone_id,
                seq=mt.seq,
                success=False,
                message=msg[:39],
            )
        )
        return

    print(f"  [dispatch] motor={motor} throttle={throttle}% duration={duration}s")
    ok, message = dispatch_motor_test(master, motor, throttle, duration)
    print(f"  [result]   {'OK' if ok else 'FAIL'}: {message}")
    link.send_ack(
        Ack(
            time_boot_ms=link.boot_ms(),
            drone_id=args.drone_id,
            seq=mt.seq,
            success=ok,
            message=message[:39],
        )
    )


def main() -> int:
    args = parse_args()

    if args.max_throttle > HARD_THROTTLE_CAP_PCT:
        sys.exit(
            f"--max-throttle {args.max_throttle} exceeds hard cap {HARD_THROTTLE_CAP_PCT}%."
        )

    print("=" * 64)
    print(" RADIO MOTOR TEST RESPONDER")
    print("=" * 64)
    print(" Confirm before proceeding:")
    print("   * every propeller is removed from every motor")
    print("   * the airframe is held down and cannot move")
    print("   * hands, cables and clothing are clear of the motor")
    print("   * battery safety switch within reach")
    print()
    answer = input("Type 'props are off' to start the responder: ").strip()
    if answer != "props are off":
        sys.exit("aborted -- confirmation phrase not entered.")

    master = open_fc(args.fc, args.fc_baud)

    print(f"opening radio {args.radio} @ {args.radio_baud} baud ...")
    try:
        link = RadioLink(
            SerialTransport(args.radio, baud=args.radio_baud),
            local_drone_id=args.drone_id,
        )
    except Exception as exc:
        sys.exit(f"could not open {args.radio}: {exc}")
    print(f"responder ready. drone_id={args.drone_id}. ctrl-c to stop.")

    t0 = time.monotonic()
    next_hb = t0
    try:
        while True:
            now = time.monotonic()
            if now >= next_hb:
                link.send_heartbeat(
                    Heartbeat(
                        time_boot_ms=link.boot_ms(),
                        drone_id=args.drone_id,
                        role=1,  # follower
                        uptime_s=int(now - t0),
                    )
                )
                next_hb = now + 0.5

            for msg in link.poll():
                if isinstance(msg, MotorTest):
                    print(
                        f"  RX MotorTest from drone_? seq={msg.seq} "
                        f"motor={msg.motor_index} thr={msg.throttle_pct}% "
                        f"dur={msg.duration_s}s"
                    )
                    handle_motor_test(args, link, master, msg)

            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nstopped by user")
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
