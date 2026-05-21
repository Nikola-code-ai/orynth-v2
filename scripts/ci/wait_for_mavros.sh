#!/usr/bin/env bash
# Block until MAVROS publishes its first /mavros/state. Fail after timeout.
set -euo pipefail

TIMEOUT_S=${TIMEOUT_S:-90}
COMPOSE_FILE=${COMPOSE_FILE:-docker/compose.dev.yaml}

deadline=$(( $(date +%s) + TIMEOUT_S ))
while (( $(date +%s) < deadline )); do
  if docker compose -f "$COMPOSE_FILE" exec -T mavros bash -c '
    source /opt/ros/humble/setup.bash
    timeout 2 ros2 topic echo --once /mavros/state >/dev/null 2>&1
  '; then
    echo "MAVROS heartbeat received"
    exit 0
  fi
  sleep 2
done

echo "ERROR: timed out waiting for /mavros/state" >&2
docker compose -f "$COMPOSE_FILE" logs --tail=80
exit 1
