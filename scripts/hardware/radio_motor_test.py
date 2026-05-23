#!/usr/bin/env python3
"""Computer-side sender for the radio motor bench test (props-off).

Sends a single ``ORYNTH_MOTOR_TEST`` frame over the SiK/RFD900x link to a
target Jetson and waits for the matching ``ORYNTH_ACK``. The Jetson side
(``radio_motor_responder.py``) is what actually talks to the FC and spins
the motor.

***  DANGER -- THIS SPINS A REAL MOTOR ON A REMOTE DRONE.  ***
***  REMOVE EVERY PROPELLER BEFORE RUNNING THIS SCRIPT.  ***

Procedure: docs/runbooks/radio_bench_tests.md § Test 2.

Example:
    python3 radio_motor_test.py \\
        --device /dev/ttyUSB0 --gcs-id 100 --target-id 1 \\
        --motor 1 --throttle 8 --duration 2
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


SAFE_THROTTLE_CEILING_PCT = 15
HARD_DURATION_CAP_S = 10


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--device",
        default=os.environ.get("RADIO_DEVICE", "/dev/ttyUSB0"),
        help="this computer's radio serial device (default /dev/ttyUSB0)",
    )
    p.add_argument(
        "--baud",
        type=int,
        default=int(os.environ.get("RADIO_BAUD", "57600")),
        help="radio baud (default 57600)",
    )
    p.add_argument(
        "--gcs-id",
        type=int,
        default=100,
        help="this sender's logical id on the radio (default 100 — any unused id)",
    )
    p.add_argument(
        "--target-id",
        type=int,
        required=True,
        help="logical drone id of the target Jetson (matches its --drone-id)",
    )
    p.add_argument(
        "--motor",
        type=int,
        default=1,
        help="motor number in ArduPilot test order, 1..8 (default 1)",
    )
    p.add_argument(
        "--throttle",
        type=int,
        default=8,
        help="throttle percent; start low (default 8)",
    )
    p.add_argument(
        "--duration",
        type=int,
        default=2,
        help="spin duration in seconds (default 2)",
    )
    p.add_argument(
        "--max-throttle",
        type=int,
        default=SAFE_THROTTLE_CEILING_PCT,
        help=f"raise the {SAFE_THROTTLE_CEILING_PCT}%% sender-side safety ceiling",
    )
    p.add_argument(
        "--ack-timeout-s",
        type=float,
        default=5.0,
        help="how long to wait for the ACK (default 5.0)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="skip the interactive 'props are off' prompt (CI use only)",
    )
    return p.parse_args()


def confirm_safety(motor: int, throttle: int, duration: int) -> None:
    print("=" * 64)
    print(
        f" RADIO MOTOR TEST -- will ask remote to spin motor #{motor} "
        f"at {throttle}% for {duration}s"
    )
    print("=" * 64)
    print(" Confirm ALL of the following before continuing:")
    print("   * every propeller is removed from every motor")
    print("   * the remote airframe is held down and cannot move")
    print("   * hands, cables and clothing are clear of the motor")
    print("   * remote responder is ready and confirmed props-off")
    print()
    answer = input("Type 'props are off' to send: ").strip()
    if answer != "props are off":
        sys.exit("aborted -- confirmation phrase not entered.")


def wait_for_ack(link: RadioLink, seq: int, timeout_s: float) -> Ack | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for msg in link.poll():
            if isinstance(msg, Ack) and msg.seq == seq:
                return msg
        time.sleep(0.02)
    return None


def main() -> int:
    args = parse_args()

    if args.throttle > args.max_throttle:
        sys.exit(
            f"throttle {args.throttle}% > ceiling {args.max_throttle}%. "
            "lower it, or raise --max-throttle deliberately."
        )
    if args.duration < 1 or args.duration > HARD_DURATION_CAP_S:
        sys.exit(f"duration must be 1..{HARD_DURATION_CAP_S}.")
    if args.motor < 1 or args.motor > 8:
        sys.exit("motor must be 1..8.")

    if not args.yes:
        confirm_safety(args.motor, args.throttle, args.duration)

    print(f"opening {args.device} @ {args.baud} baud ...")
    try:
        link = RadioLink(
            SerialTransport(args.device, baud=args.baud),
            local_drone_id=args.gcs_id,
        )
    except Exception as exc:
        sys.exit(f"could not open {args.device}: {exc}")

    # A short pre-roll: a heartbeat or two so the responder logs the peer.
    link.send_heartbeat(
        Heartbeat(time_boot_ms=link.boot_ms(), drone_id=args.gcs_id,
                  role=0, uptime_s=0)
    )
    time.sleep(0.3)

    seq = int(time.monotonic() * 1000) & 0xFFFF
    print(f"sending MotorTest to drone_{args.target_id} seq={seq} ...")
    link.send_motor_test(
        MotorTest(
            time_boot_ms=link.boot_ms(),
            drone_id=args.target_id,
            seq=seq,
            motor_index=args.motor,
            throttle_pct=args.throttle,
            duration_s=args.duration,
        )
    )

    print(f"waiting up to {args.ack_timeout_s:.1f}s for ACK ...")
    ack = wait_for_ack(link, seq, args.ack_timeout_s)
    link.close()

    if ack is None:
        print("FAIL: no ACK received. check the responder log and the radio link.")
        return 2
    if not ack.success:
        print(f"FAIL: remote refused: {ack.message}")
        return 3
    print(f"OK: {ack.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
