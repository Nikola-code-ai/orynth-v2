#!/usr/bin/env python3
"""Flight-controller link smoke test for Orynth hardware bring-up.

A standalone pymavlink diagnostic that runs *on the Jetson Nano* -- no ROS 2
or MAVROS required. It opens the serial link to the ArduPilot flight
controller, waits for a MAVLink heartbeat, and prints a short health report:
vehicle identity, arm state, flight mode, battery, GPS and attitude.

This script never arms the vehicle and never commands an actuator, so it is
safe to run even with propellers attached.

Example:
    python3 fc_link_test.py --port /dev/ttyTHS1 --baud 57600
"""

import argparse
import math
import sys
import time

try:
    from pymavlink import mavutil
except ImportError:
    sys.exit("pymavlink is not installed. Run: pip install pymavlink")


# ArduPilot Copter mode numbers (HEARTBEAT.custom_mode) we are likely to see.
COPTER_MODES = {
    0: "STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "AUTO", 4: "GUIDED",
    5: "LOITER", 6: "RTL", 7: "CIRCLE", 9: "LAND", 16: "POSHOLD",
    17: "BRAKE", 20: "GUIDED_NOGPS",
}

GPS_FIX = {
    0: "no GPS", 1: "no fix", 2: "2D fix", 3: "3D fix",
    4: "DGPS", 5: "RTK float", 6: "RTK fixed",
}


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--port", default="/dev/ttyTHS1",
                   help="serial device wired to the FC (default: %(default)s)")
    p.add_argument("--baud", type=int, default=57600,
                   help="baud rate; ArduPilot TELEM ports default to 57600 "
                        "(default: %(default)s)")
    p.add_argument("--heartbeat-timeout", type=float, default=15.0,
                   help="seconds to wait for the first heartbeat")
    p.add_argument("--watch", type=float, default=8.0,
                   help="seconds to stream live telemetry after connecting")
    return p.parse_args()


def name_of(enum, value):
    """Human-readable name for a MAVLink enum value, numeric fallback."""
    try:
        return mavutil.mavlink.enums[enum][value].name
    except KeyError:
        return "%s(%d)" % (enum, value)


def connect(port, baud, timeout):
    print("Opening %s @ %d baud ..." % (port, baud))
    try:
        master = mavutil.mavlink_connection(port, baud=baud)
    except Exception as exc:        # serial errors, missing device, perms
        sys.exit("Could not open %s: %s" % (port, exc))

    print("Waiting up to %.0fs for a heartbeat ..." % timeout)
    hb = master.wait_heartbeat(timeout=timeout)
    if hb is None:
        sys.exit(
            "No heartbeat. Check, in order: TX/RX not swapped, baud matches "
            "the FC's SERIALx_BAUD, the port is not held by a console getty "
            "(lsof /dev/ttyTHS1), and the FC is powered."
        )
    return master, hb


def report_heartbeat(master, hb):
    armed = bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
    mode = COPTER_MODES.get(hb.custom_mode, "mode#%d" % hb.custom_mode)
    print()
    print("=== Heartbeat received ===")
    print("  link target   : system %d, component %d"
          % (master.target_system, master.target_component))
    print("  autopilot     : %s" % name_of("MAV_AUTOPILOT", hb.autopilot))
    print("  vehicle type  : %s" % name_of("MAV_TYPE", hb.type))
    print("  system status : %s" % name_of("MAV_STATE", hb.system_status))
    print("  flight mode   : %s" % mode)
    print("  armed         : %s" % ("YES  <-- vehicle is armed!" if armed
                                    else "no (disarmed)"))


def stream_telemetry(master, seconds):
    """Collect a few seconds of telemetry; return the latest of each type."""
    master.mav.request_data_stream_send(
        master.target_system, master.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1,   # 4 Hz, start streaming
    )
    print()
    print("Streaming telemetry for %.0fs ..." % seconds)
    latest = {}
    deadline = time.time() + seconds
    while time.time() < deadline:
        msg = master.recv_match(blocking=True, timeout=1.0)
        if msg is None:
            continue
        kind = msg.get_type()
        if kind == "STATUSTEXT":
            print("  [FC] %s" % msg.text)
        elif kind in ("SYS_STATUS", "GPS_RAW_INT", "ATTITUDE"):
            latest[kind] = msg
    return latest


def report_telemetry(latest):
    print()
    print("=== Telemetry snapshot ===")

    sysst = latest.get("SYS_STATUS")
    if sysst is not None:
        volts = sysst.voltage_battery / 1000.0
        amps = (sysst.current_battery / 100.0
                if sysst.current_battery != -1 else None)
        print("  battery       : %.2f V%s, %d%% remaining"
              % (volts,
                 ", %.1f A" % amps if amps is not None else "",
                 sysst.battery_remaining))
    else:
        print("  battery       : no SYS_STATUS received")

    gps = latest.get("GPS_RAW_INT")
    if gps is not None:
        print("  gps           : %s, %d satellites"
              % (GPS_FIX.get(gps.fix_type, "?"), gps.satellites_visible))
    else:
        print("  gps           : no GPS_RAW_INT received")

    att = latest.get("ATTITUDE")
    if att is not None:
        print("  attitude      : roll %+.1f  pitch %+.1f  yaw %+.1f (deg)"
              % (math.degrees(att.roll), math.degrees(att.pitch),
                 math.degrees(att.yaw)))
    else:
        print("  attitude      : no ATTITUDE received")


def main():
    args = parse_args()
    master, hb = connect(args.port, args.baud, args.heartbeat_timeout)
    report_heartbeat(master, hb)
    latest = stream_telemetry(master, args.watch)
    report_telemetry(latest)
    print()
    print("Link OK -- the serial path Jetson <-> flight controller works.")
    print("Next: remove ALL propellers, then run motor_test.py.")


if __name__ == "__main__":
    main()
