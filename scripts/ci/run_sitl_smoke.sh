#!/usr/bin/env bash
# Phase 1 SITL smoke test — arm, GUIDED takeoff to 5 m, waypoint to (10,0,5),
# land. The mission is driven through swarm_control.sitl_mission, i.e. the
# MavrosAdapter path (PLAN section I, file #4) — not raw `ros2 service call`.
#
# Run by .github/workflows/sitl_smoke.yml on every PR. Test budget: <8 min
# with warm image caches (image builds dominate a cold run).
#
# Env:
#   SMOKE_RECORD=1   also capture accept/phase1.mcap for the acceptance log.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=(docker compose -f docker/compose.dev.yaml)
RECORD="${SMOKE_RECORD:-0}"

cleanup() {
  "${COMPOSE[@]}" logs --no-color --tail=200 > /tmp/orynth_sitl_smoke.log 2>&1 || true
  "${COMPOSE[@]}" down -v --remove-orphans || true
}
trap cleanup EXIT

echo "==> Building images (cached layers reused; cold ArduPilot build is slow)..."
docker buildx build --load -f docker/base.Dockerfile -t orynth-base:dev .
docker buildx build --load -f docker/sitl.Dockerfile \
  --build-arg BASE_TAG=orynth-base:dev -t orynth-sitl:dev .

echo "==> Cold-starting SITL + companion (MAVROS + Foxglove)..."
start=$(date +%s)
"${COMPOSE[@]}" up -d --wait --wait-timeout 300
echo "==> Stack healthy in $(( $(date +%s) - start )) s (PLAN gate: <60 s)"

echo "==> Confirming MAVROS heartbeat..."
bash "$REPO_ROOT/scripts/ci/wait_for_mavros.sh"

if [ "$RECORD" = "1" ]; then
  echo "==> Recording acceptance bag..."
  "${COMPOSE[@]}" exec -d companion bash -lc '
    source /opt/ros/humble/setup.bash
    rm -rf /tmp/phase1_bag
    ros2 bag record -s mcap -o /tmp/phase1_bag \
      /mavros/state /mavros/local_position/pose /mavros/setpoint_raw/local
  '
fi

echo "==> Running Phase 1 mission via swarm_control.sitl_mission..."
"${COMPOSE[@]}" exec -T companion bash -lc '
  source /opt/ros/humble/setup.bash
  source /opt/overlay/setup.bash
  ros2 run swarm_control sitl_mission
'

if [ "$RECORD" = "1" ]; then
  echo "==> Finalizing acceptance bag..."
  "${COMPOSE[@]}" exec -T companion pkill -INT -f "ros2 bag record" || true
  sleep 4
  mkdir -p "$REPO_ROOT/accept"
  bag_mcap="$(docker exec orynth-companion \
    bash -lc 'ls /tmp/phase1_bag/*.mcap 2>/dev/null | head -n1' || true)"
  if [ -n "$bag_mcap" ]; then
    docker cp "orynth-companion:${bag_mcap}" "$REPO_ROOT/accept/phase1.mcap"
    echo "==> Wrote accept/phase1.mcap"
  else
    echo "WARN: no acceptance bag produced" >&2
  fi
fi

echo "==> Phase 1 smoke test PASS"
