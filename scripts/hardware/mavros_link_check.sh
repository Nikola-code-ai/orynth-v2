#!/usr/bin/env bash
# MAVROS <-> flight-controller link check -- hardware bring-up, Part 2.
#
# The ROS-layer equivalent of fc_link_test.py: instead of talking raw MAVLink,
# it inspects the MAVROS topic surface and asserts the FCU link is live.
#
# Runs INSIDE the orynth-companion container, after `make hw-up`:
#
#   docker exec -it orynth-companion \
#     bash /workspace/scripts/hardware/mavros_link_check.sh
#
# (or simply `make hw-check`). Exit 0 = link healthy.
set -uo pipefail

source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"

ECHO_TIMEOUT=6

show() {  # show <topic> -- print one message, or a 'no message' note
    local topic="$1"
    if ! timeout "${ECHO_TIMEOUT}" ros2 topic echo --once "${topic}" 2>/dev/null
    then
        echo "  (no message on ${topic} within ${ECHO_TIMEOUT}s)"
    fi
}

echo "=== MAVROS topic surface ==="
count=$(ros2 topic list 2>/dev/null | grep -c '^/mavros/' || true)
echo "  ${count} /mavros/* topics advertised"
echo

echo "=== /mavros/state (link, mode, arm) ==="
state=$(timeout "${ECHO_TIMEOUT}" ros2 topic echo --once /mavros/state 2>/dev/null || true)
echo "${state:-  (no /mavros/state -- is the MAVROS node running?)}"
echo

echo "=== /mavros/battery ==="
show /mavros/battery
echo

echo "=== /mavros/imu/data ==="
show /mavros/imu/data
echo

echo "=== /mavros/global_position/global (EKF-fused GPS) ==="
show /mavros/global_position/global
echo

if grep -iqE 'connected:[[:space:]]*true' <<<"${state}"; then
    echo "RESULT: PASS -- MAVROS has a live link to the flight controller."
    exit 0
fi

echo "RESULT: FAIL -- MAVROS is up but not connected to the FC."
echo "  Check, in order:"
echo "    * FCU_URL device path and baud match the FC's SERIALx_BAUD"
echo "    * the serial device is mapped into the container (devices:)"
echo "    * TX/RX are not swapped and the FC is powered"
echo "    * nothing else on the host holds the port (MAVProxy, a getty)"
exit 1
