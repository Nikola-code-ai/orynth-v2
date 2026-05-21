#!/usr/bin/env bash
# Build the ROS 2 workspace. Fails loudly if any dependency is unpinned (ADR 0007).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Refuse to build if pin sentinels are still present.
if grep -RnE "^\s*version:\s*0+\s*$" orynth.repos >/dev/null; then
  echo "ERROR: orynth.repos has unset SHAs (ADR 0007). Run scripts/build/refresh_pins.sh." >&2
  exit 1
fi
if grep -RE "^FROM [^@]+:[^@]+\s*$" docker/ >/dev/null; then
  echo "ERROR: docker/ has unpinned FROMs (ADR 0007). Pin by @sha256:..." >&2
  exit 1
fi

source /opt/ros/humble/setup.bash

cd ros2_ws
# Fetch pinned sources if .repos is present and not already imported.
if [ -f ../orynth.repos ] && [ ! -d src/.vcs-imported ]; then
  vcs import src < ../orynth.repos
  mkdir -p src/.vcs-imported
fi

rosdep install --from-paths src --ignore-src -y \
  --skip-keys "behaviortree_cpp octomap_server rtabmap_ros foxglove_bridge"

colcon build --symlink-install --packages-skip swarm_hardware
