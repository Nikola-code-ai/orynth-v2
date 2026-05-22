#!/usr/bin/env bash
# Compose-internal bringup for the Phase 1 single-drone companion container.
#
# Builds the swarm_control + swarm_bringup overlay from the (read-only) mounted
# workspace into /opt/overlay, then launches MAVROS + the Foxglove bridge via
# swarm_bringup/sitl_single.launch.py.
#
# Runs inside the orynth-base image; docker/entrypoint.sh has already sourced
# /opt/ros/${ROS_DISTRO}/setup.bash before exec-ing this script.
set -euo pipefail

FCU_URL="${FCU_URL:-tcp://127.0.0.1:5760@}"
FOXGLOVE_PORT="${FOXGLOVE_PORT:-8765}"

echo "==> Building swarm_control + swarm_bringup overlay -> /opt/overlay"
cd /workspace/ros2_ws
# --log-base is a global colcon option (before the verb); --build-base /
# --install-base are `build` verb options (after it).
colcon --log-base /tmp/overlay_log build \
  --packages-select swarm_control swarm_bringup \
  --build-base /tmp/overlay_build \
  --install-base /opt/overlay

# colcon/ROS setup scripts reference unset vars (COLCON_TRACE, ...) and are not
# safe under `set -u` — disable nounset just for the source.
set +u
# shellcheck disable=SC1091
source /opt/overlay/setup.bash
set -u

echo "==> Launching MAVROS + Foxglove bridge (fcu_url=${FCU_URL})"
exec ros2 launch swarm_bringup sitl_single.launch.py \
  fcu_url:="${FCU_URL}" \
  foxglove_port:="${FOXGLOVE_PORT}"
