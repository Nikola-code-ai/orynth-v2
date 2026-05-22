#!/usr/bin/env bash
# Phase 2 acceptance gate — 5-drone SITL swarm + diamond formation.
#
# Builds the images, cold-starts the headless swarm stack, drives the
# swarm_server services (takeoff -> engage diamond -> hold -> land) and asserts
# the formation drift converges under 0.5 m mean (PLAN section D, Phase 2).
#
# Run by .github/workflows/sitl_smoke.yml (nightly). Env:
#   SWARM_HOLD_S=<sec>   diamond-hold duration (default 60)
#   SWARM_RECORD=1       also capture accept/phase2.mcap
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=(docker compose -f docker/compose.swarm.yaml)
HOLD_S="${SWARM_HOLD_S:-60}"
RECORD="${SWARM_RECORD:-0}"

cleanup() {
  "${COMPOSE[@]}" logs --no-color > /tmp/orynth_swarm_smoke.log 2>&1 || true
  "${COMPOSE[@]}" down -v --remove-orphans || true
}
trap cleanup EXIT

# Run a ROS 2 command inside the companion, overlay sourced.
companion() {
  "${COMPOSE[@]}" exec -T companion bash -lc \
    "source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash; $*"
}

echo "==> Building images (cached layers reused)..."
docker buildx build --load -f docker/base.Dockerfile -t orynth-base:dev .
docker buildx build --load -f docker/sitl.Dockerfile \
  --build-arg BASE_TAG=orynth-base:dev -t orynth-sitl:dev .

echo "==> Cold-starting the 5-drone swarm (headless pure-SITL)..."
start=$(date +%s)
SWARM_HEADLESS=1 SWARM_GAZEBO=0 "${COMPOSE[@]}" up -d --wait --wait-timeout 360
echo "==> Stack healthy in $(( $(date +%s) - start )) s"

echo "==> Waiting for swarm_server services..."
deadline=$(( $(date +%s) + 120 ))
until companion "ros2 service list" 2>/dev/null | grep -q "/swarm/takeoff"; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "ERROR: /swarm/takeoff never appeared" >&2
    exit 1
  fi
  sleep 3
done

if [ "$RECORD" = "1" ]; then
  echo "==> Recording acceptance bag..."
  "${COMPOSE[@]}" exec -d companion bash -lc '
    source /opt/ros/humble/setup.bash
    rm -rf /tmp/phase2_bag
    ros2 bag record -s mcap -o /tmp/phase2_bag \
      /swarm/status /drone_0/mavros/local_position/pose \
      /drone_1/mavros/local_position/pose /drone_2/mavros/local_position/pose
  '
fi

echo "==> /swarm/takeoff to 5 m (all drones)..."
companion "ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff '{altitude_m: 5.0}'" \
  | tee /tmp/swarm_takeoff.txt
grep -q "success=True" /tmp/swarm_takeoff.txt

echo "==> /swarm/engage_formation diamond..."
companion "ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation \
  '{formation_name: diamond, spacing_m: 4.0, heading_deg: 0.0}'" \
  | tee /tmp/swarm_formation.txt
grep -q "success=True" /tmp/swarm_formation.txt

echo "==> Holding diamond for ${HOLD_S} s..."
sleep "$HOLD_S"

echo "==> /swarm/land (all drones)..."
companion "ros2 service call /swarm/land std_srvs/srv/Trigger '{}'" \
  | tee /tmp/swarm_land.txt
grep -q "success=True" /tmp/swarm_land.txt

if [ "$RECORD" = "1" ]; then
  "${COMPOSE[@]}" exec -T companion pkill -INT -f "ros2 bag record" || true
  sleep 4
  mkdir -p "$REPO_ROOT/accept"
  bag="$(docker exec orynth-swarm-companion \
    bash -lc 'ls /tmp/phase2_bag/*.mcap 2>/dev/null | head -n1' || true)"
  if [ -n "$bag" ]; then
    docker cp "orynth-swarm-companion:${bag}" "$REPO_ROOT/accept/phase2.mcap"
    echo "==> Wrote accept/phase2.mcap"
  fi
fi

echo "==> Checking diamond formation drift (PLAN gate: <0.5 m mean)..."
"${COMPOSE[@]}" logs --no-color companion > /tmp/orynth_swarm_full.log 2>&1 || true
mapfile -t drifts < <(
  grep -oP 'drift mean=\K[0-9.]+' /tmp/orynth_swarm_full.log | tail -n 15
)
if [ "${#drifts[@]}" -lt 5 ]; then
  echo "ERROR: only ${#drifts[@]} drift samples — formation loop did not run" >&2
  exit 1
fi
worst="$(printf '%s\n' "${drifts[@]}" | sort -g | tail -n1)"
echo "==> worst drift over the last ${#drifts[@]} samples: ${worst} m"
awk -v w="$worst" 'BEGIN { exit (w < 0.5) ? 0 : 1 }' || {
  echo "FAIL: diamond drift ${worst} m exceeds the 0.5 m gate" >&2
  exit 1
}

echo "==> Phase 2 swarm smoke PASS"
