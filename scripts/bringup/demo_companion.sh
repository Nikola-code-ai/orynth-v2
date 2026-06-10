#!/usr/bin/env bash
# Phase 2.5b demo companion-container entrypoint (one per Jetson).
#
# Builds the swarm overlay (swarm_bringup + its dependency closure) from the
# read-only mounted workspace into /opt/overlay, then launches this drone's
# hardware bringup via swarm_bringup/hw_drone.launch.py:
#
#   * every Jetson  -> one namespaced MAVROS against the wired flight controller
#   * leader Jetson -> + Foxglove bridge + swarm_server  (WITH_SWARM_SERVER=1)
#
# Runs inside orynth-base; docker/entrypoint.sh has already sourced
# /opt/ros/${ROS_DISTRO}/setup.bash. `set -u` is intentionally omitted — the
# colcon-generated setup scripts dereference unset vars (COLCON_TRACE, ...).
set -eo pipefail

echo "==> Building swarm overlay -> /opt/overlay (swarm_bringup + dependency closure)"
cd /workspace/ros2_ws
# --packages-up-to pulls in swarm_bringup's full dependency closure
# (swarm_msgs IDL, swarm_control, swarm_sim, swarm_perception) — swarm_server
# needs swarm_msgs + swarm_control built, even on follower Jetsons.
colcon --log-base /tmp/overlay_log build \
  --packages-up-to swarm_bringup swarm_radio \
  --build-base /tmp/overlay_build \
  --install-base /opt/overlay

# shellcheck disable=SC1091
source /opt/overlay/setup.bash

echo "==> Launching demo drone: DRONE_ID=${DRONE_ID:-0} WITH_SWARM_SERVER=${WITH_SWARM_SERVER:-0}"
exec ros2 launch swarm_bringup hw_drone.launch.py
