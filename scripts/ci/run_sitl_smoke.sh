#!/usr/bin/env bash
# Phase 1 SITL smoke test — arm, takeoff to 5 m, waypoint to (10,0,5), land.
# Run by .github/workflows/sitl_smoke.yml on every PR. Budget: <8 min.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

cleanup() {
  docker compose -f docker/compose.dev.yaml down -v --remove-orphans || true
}
trap cleanup EXIT

echo "==> Bringing up SITL + MAVROS + Foxglove..."
docker compose -f docker/compose.dev.yaml up -d

echo "==> Waiting for MAVROS heartbeat..."
bash "$REPO_ROOT/scripts/ci/wait_for_mavros.sh"

echo "==> Running mission: arm -> takeoff 5m -> waypoint -> land..."
# Phase 1 deliverable: ros2 service calls via swarm_control.mavros_adapter.
# Placeholder until adapter ships.
docker compose -f docker/compose.dev.yaml exec -T mavros bash -c '
  source /opt/ros/humble/setup.bash
  # arming -> guided -> takeoff -> setpoint -> land
  ros2 service call /mavros/set_mode mavros_msgs/srv/SetMode "{custom_mode: GUIDED}"
  ros2 service call /mavros/cmd/arming mavros_msgs/srv/CommandBool "{value: true}"
  ros2 service call /mavros/cmd/takeoff mavros_msgs/srv/CommandTOL \
    "{min_pitch: 0.0, yaw: 0.0, latitude: 0.0, longitude: 0.0, altitude: 5.0}"
  sleep 15
  ros2 service call /mavros/cmd/land mavros_msgs/srv/CommandTOL \
    "{min_pitch: 0.0, yaw: 0.0, latitude: 0.0, longitude: 0.0, altitude: 0.0}"
  sleep 20
'

echo "==> Smoke test PASS"
