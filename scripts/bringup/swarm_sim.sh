#!/usr/bin/env bash
# Phase 2 sim-container entrypoint.
#
# Starts the swarm flight simulation via swarm_sim.sitl_launcher — pure-SITL
# 'quad' physics by default (headless, frame-clean, what CI runs), or Gazebo
# Harmonic when SWARM_GAZEBO=1 (with the GUI unless SWARM_HEADLESS=1).
#
# Runs inside orynth-sitl; the repo is mounted read-only at /workspace.
set -eo pipefail

DRONES="${DRONE_COUNT:-5}"
ARGS=(--drones "$DRONES")

if [ "${SWARM_GAZEBO:-0}" = "1" ]; then
  ARGS+=(--gazebo)
  [ "${SWARM_HEADLESS:-0}" = "1" ] && ARGS+=(--headless)
else
  ARGS+=(--no-gazebo)
fi

echo "==> swarm_sim: ${DRONES} drones, gazebo=${SWARM_GAZEBO:-0}, headless=${SWARM_HEADLESS:-1}"
# cd into the package root so `-m swarm_sim.<mod>` resolves to the mounted
# source (cwd is sys.path[0]) — never a stale colcon install/ tree.
cd /workspace/ros2_ws/src/swarm_sim
# exec so sitl_launcher is PID 1 and receives docker's SIGTERM directly.
exec python3 -m swarm_sim.sitl_launcher "${ARGS[@]}"
