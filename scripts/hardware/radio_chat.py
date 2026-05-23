#!/usr/bin/env python3
"""Radio bench chat: prove the SiK/RFD900x link carries Orynth frames.

Bidirectional smoke test for the inter-drone radio (ADR 0009). Run this on
**both** ends of a configured radio pair — your laptop and a Jetson, or two
laptops, or two Jetsons. Each side sends a `Heartbeat` every 0.5 s and a
synthetic `DroneState` every 1 s, prints every frame it receives, and shows
the live age of the most recent peer frame.

Pass criteria:
  - Within ~1 s of starting both sides, each prints frames from the other.
  - `link age` stays under ~0.6 s on both sides.

This script needs no ROS, no FC, no airframe. It uses the same wire format
that `radio_bridge` uses in flight, so a clean run here proves the radio
firmware, antennas, NETID, and udev rule are all good.

Procedure: docs/runbooks/radio_bench_tests.md § Test 1.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

# Add swarm_radio to sys.path so this script runs without colcon/ROS.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "ros2_ws" / "src" / "swarm_radio"))

from swarm_radio.radio_link import (  # noqa: E402
    DroneState,
    Heartbeat,
    RadioLink,
    SerialTransport,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--device",
        default=os.environ.get("RADIO_DEVICE", "/dev/ttyUSB_RFD"),
        help="serial device of the radio (default /dev/ttyUSB_RFD)",
    )
    p.add_argument(
        "--baud",
        type=int,
        default=int(os.environ.get("RADIO_BAUD", "57600")),
        help="radio serial baud (must match radio's SERIAL_SPEED; default 57600)",
    )
    p.add_argument(
        "--drone-id",
        type=int,
        required=True,
        help="this node's logical id (0=leader; pick anything unique on the link)",
    )
    p.add_argument(
        "--peer-id",
        type=int,
        default=None,
        help="optional: only show link age for this peer id (default: any peer)",
    )
    p.add_argument(
        "--state-rate-hz",
        type=float,
        default=1.0,
        help="DroneState send rate, Hz (default 1.0)",
    )
    p.add_argument(
        "--heartbeat-rate-hz",
        type=float,
        default=2.0,
        help="Heartbeat send rate, Hz (default 2.0)",
    )
    p.add_argument(
        "--duration-s",
        type=float,
        default=0.0,
        help="exit after N seconds (0 = run until Ctrl-C)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    print(f"opening {args.device} @ {args.baud} baud ...")
    try:
        link = RadioLink(
            SerialTransport(args.device, baud=args.baud),
            local_drone_id=args.drone_id,
        )
    except Exception as exc:  # serial.SerialException, OSError, etc.
        print(f"FAILED to open {args.device}: {exc}", file=sys.stderr)
        return 1
    print(f"link open. local drone_id={args.drone_id}. ctrl-c to stop.")

    hb_period = 1.0 / max(0.1, args.heartbeat_rate_hz)
    state_period = 1.0 / max(0.1, args.state_rate_hz)

    t0 = time.monotonic()
    next_hb = t0
    next_state = t0
    next_status = t0 + 1.0
    deadline = t0 + args.duration_s if args.duration_s > 0 else math.inf

    try:
        while time.monotonic() < deadline:
            now = time.monotonic()

            if now >= next_hb:
                link.send_heartbeat(
                    Heartbeat(
                        time_boot_ms=link.boot_ms(),
                        drone_id=args.drone_id,
                        role=0,
                        uptime_s=int(now - t0),
                    )
                )
                next_hb = now + hb_period

            if now >= next_state:
                # Synthetic moving pose so the receiver sees something changing.
                t = now - t0
                link.send_drone_state(
                    DroneState(
                        time_boot_ms=link.boot_ms(),
                        drone_id=args.drone_id,
                        x=math.cos(t * 0.2),
                        y=math.sin(t * 0.2),
                        z=2.0,
                        yaw_rad=(t * 0.1) % (2 * math.pi),
                        armed=False,
                        ekf_ok=True,
                        battery_pct=100,
                        mode="BENCH",
                    )
                )
                next_state = now + state_period

            for msg in link.poll():
                kind = type(msg).__name__
                drone_id = getattr(msg, "drone_id", "?")
                if isinstance(msg, DroneState):
                    extra = f" pos=({msg.x:+.2f},{msg.y:+.2f},{msg.z:+.2f}) mode={msg.mode}"
                elif isinstance(msg, Heartbeat):
                    extra = f" role={msg.role} uptime={msg.uptime_s}s"
                else:
                    extra = ""
                print(f"  RX {kind:<12} from drone_{drone_id}{extra}")

            if now >= next_status:
                peer = args.peer_id
                if peer is not None:
                    age = link.peer_age_s(peer)
                    label = f"drone_{peer}"
                else:
                    # Best (smallest) age among known peers, ignoring self.
                    ages = {
                        pid: link.peer_age_s(pid)
                        for pid in link._peer_rx_mono  # type: ignore[attr-defined]
                        if pid != args.drone_id
                    }
                    if not ages:
                        age = float("inf")
                        label = "any-peer"
                    else:
                        pid, age = min(ages.items(), key=lambda kv: kv[1])
                        label = f"drone_{pid}"
                age_str = f"{age:.2f}s" if math.isfinite(age) else "no frames yet"
                print(f"  [status] link age ({label}) = {age_str}")
                next_status = now + 1.0

            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nstopped by user")
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
