#!/usr/bin/env python3
"""Single-motor low-throttle bench test (MAV_CMD_DO_MOTOR_TEST).

  *** DANGER -- THIS SPINS A REAL MOTOR. ***
  *** REMOVE EVERY PROPELLER BEFORE RUNNING THIS SCRIPT. ***

Uses ArduPilot's dedicated motor-test command, which spins one motor at a
fixed throttle for a fixed time *without arming the vehicle* and stops it
automatically when the timeout expires. This is the correct, supported way
to bench-test a motor -- far safer than arming into a flight mode.

Run fc_link_test.py first to confirm the link is healthy.

Example (motor 1, 8% throttle, 3 second spin):
    python3 motor_test.py --port /dev/ttyTHS1 --motor 1 --throttle 8 --timeout 3
"""

import argparse
import sys
import time

try:
    from pymavlink import mavutil
except ImportError:
    sys.exit("pymavlink is not installed. Run: pip install pymavlink")


# Refuse a throttle above this unless --max-throttle is raised deliberately.
SAFE_THROTTLE_CEILING = 15.0


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--port", default="/dev/ttyTHS1")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument(
        "--motor",
        type=int,
        default=1,
        help="motor number in ArduPilot test order (1-indexed)",
    )
    p.add_argument(
        "--throttle",
        type=float,
        default=8.0,
        help="throttle percent; start low, raise in small steps",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="seconds the motor spins before the FC stops it",
    )
    p.add_argument(
        "--max-throttle",
        type=float,
        default=SAFE_THROTTLE_CEILING,
        help="raise the throttle safety ceiling (bench use only)",
    )
    return p.parse_args()


def confirm_safety(args):
    print("=" * 64)
    print(
        " MOTOR TEST -- will spin motor #%d at %.0f%% for %.0fs"
        % (args.motor, args.throttle, args.timeout)
    )
    print("=" * 64)
    print(" Confirm ALL of the following before continuing:")
    print("   * every propeller is removed from every motor")
    print("   * the airframe is held down and cannot move")
    print("   * hands, cables and clothing are clear of the motor")
    print("   * you can cut power instantly (safety switch / battery)")
    print()
    answer = input("Type 'props are off' to proceed: ").strip()
    if answer != "props are off":
        sys.exit("Aborted -- confirmation phrase not entered.")


def send_motor_test(master, motor, throttle, timeout):
    """Issue MAV_CMD_DO_MOTOR_TEST for a single motor."""
    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST,
        0,  # confirmation
        motor,  # p1: motor number
        mavutil.mavlink.MOTOR_TEST_THROTTLE_PERCENT,  # p2: throttle type
        throttle,  # p3: throttle value
        timeout,  # p4: spin time (s)
        0,  # p5: motor count (one)
        0,  # p6: test order
        0,  # p7: unused
    )


def wait_for_ack(master):
    """Return the COMMAND_ACK for the motor-test command, or None."""
    deadline = time.time() + 3.0
    while time.time() < deadline:
        m = master.recv_match(type="COMMAND_ACK", blocking=True, timeout=1.0)
        if m is not None and m.command == mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST:
            return m
    return None


def main():
    args = parse_args()

    if args.throttle > args.max_throttle:
        sys.exit(
            "Throttle %.0f%% exceeds the %.0f%% ceiling. Lower it, or "
            "raise --max-throttle deliberately." % (args.throttle, args.max_throttle)
        )

    print("Opening %s @ %d baud ..." % (args.port, args.baud))
    try:
        master = mavutil.mavlink_connection(args.port, baud=args.baud)
    except Exception as exc:
        sys.exit("Could not open %s: %s" % (args.port, exc))

    hb = master.wait_heartbeat(timeout=15)
    if hb is None:
        sys.exit("No heartbeat -- run fc_link_test.py to debug the link.")
    if hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
        sys.exit("Vehicle is ARMED. Disarm before motor testing.")
    print("Heartbeat OK, vehicle disarmed.")

    confirm_safety(args)

    print()
    for n in (3, 2, 1):
        print("  spinning in %d ..." % n)
        time.sleep(1)

    send_motor_test(master, args.motor, args.throttle, args.timeout)

    ack = wait_for_ack(master)
    if ack is None:
        print("No COMMAND_ACK received -- motor may or may not have run.")
    elif ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
        print("Motor test ACCEPTED -- motor #%d should be spinning." % args.motor)
    else:
        result = mavutil.mavlink.enums["MAV_RESULT"][ack.result].name
        print("Motor test REJECTED by FC: %s" % result)
        print(
            "Common causes: safety switch still engaged, frame not "
            "configured (FRAME_CLASS / FRAME_TYPE), or ESCs unpowered."
        )

    # Watch the spin window, surfacing any FC status messages.
    try:
        end = time.time() + args.timeout + 1.0
        while time.time() < end:
            m = master.recv_match(type="STATUSTEXT", blocking=True, timeout=1.0)
            if m is not None:
                print("  [FC] %s" % m.text)
    except KeyboardInterrupt:
        print("\nCtrl-C -- sending stop command ...")
        send_motor_test(master, args.motor, 0, 0)

    print("Done. The FC stops the motor automatically at timeout.")


if __name__ == "__main__":
    main()
