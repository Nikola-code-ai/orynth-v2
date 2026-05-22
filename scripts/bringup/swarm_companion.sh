#!/usr/bin/env bash
# Phase 2 companion-container entrypoint.
#
# Builds the swarm overlay (swarm_bringup and its dependency closure —
# swarm_msgs, swarm_control, swarm_sim, swarm_perception) from the read-only
# mounted workspace into /opt/overlay, then launches N namespaced MAVROS
# instances + the Foxglove bridge + swarm_server_node via
# swarm_bringup/sitl_swarm.launch.py.
#
# Runs inside orynth-base; docker/entrypoint.sh has already sourced
# /opt/ros/${ROS_DISTRO}/setup.bash. `set -u` is intentionally omitted — the
# colcon-generated setup scripts dereference unset vars (COLCON_TRACE, ...).
set -eo pipefail

echo "==> Building swarm overlay -> /opt/overlay (swarm_bringup + dependency closure)"
cd /workspace/ros2_ws
# --packages-up-to pulls in swarm_bringup's full dependency closure
# (swarm_msgs IDL, swarm_control, swarm_sim, swarm_perception) — an ament_cmake
# package's exec_depends must be built for its colcon cmake task to pass.
# --log-base is a global colcon option (before the verb); --build-base /
# --install-base are `build` verb options (after it).
colcon --log-base /tmp/overlay_log build \
  --packages-up-to swarm_bringup \
  --build-base /tmp/overlay_build \
  --install-base /opt/overlay

# shellcheck disable=SC1091
source /opt/overlay/setup.bash

echo "==> Launching swarm: DRONE_COUNT=${DRONE_COUNT:-5} SIM_HOST=${SIM_HOST:-sim}"
exec ros2 launch swarm_bringup sitl_swarm.launch.py
