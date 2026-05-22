#!/usr/bin/env bash
# Phase 2.5a acceptance gate — leader-follow in the SITL swarm (PLAN section D).
#
# Builds the images, cold-starts the headless 5-drone swarm, then drives the
# leader-follow demo end to end:
#
#   takeoff -> /swarm/follow_leader (engage) -> the operator "flies" the leader
#   with /swarm/drone_0/manual_goto -> the four followers track the diamond
#   live -> the leader-pose watchdog is exercised -> disengage -> land.
#
# It asserts the settled follower drift converges under 0.5 m mean and that the
# watchdog demonstrably engages on a simulated leader-pose dropout.
#
# This is the automatable, CI-friendly gate — headless pure-SITL, no Gazebo
# rendering. For the on-screen Gazebo version of the same demo run
# `make swarm-up` and call the services by hand (see COMMANDS.md).
#
# Env:
#   LEADERFOLLOW_HOLD_S=<sec>   settled-hold duration before the drift check (default 25)
#   LEADERFOLLOW_RECORD=1       also capture accept/leaderfollow_sitl.mcap
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=(docker compose -f docker/compose.swarm.yaml)
HOLD_S="${LEADERFOLLOW_HOLD_S:-25}"
RECORD="${LEADERFOLLOW_RECORD:-0}"

cleanup() {
  "${COMPOSE[@]}" logs --no-color > /tmp/orynth_leaderfollow.log 2>&1 || true
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

echo "==> Waiting for the /swarm/follow_leader service..."
deadline=$(( $(date +%s) + 120 ))
until companion "ros2 service list" 2>/dev/null | grep -q "/swarm/follow_leader"; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "ERROR: /swarm/follow_leader never appeared" >&2
    exit 1
  fi
  sleep 3
done

if [ "$RECORD" = "1" ]; then
  echo "==> Recording acceptance bag..."
  "${COMPOSE[@]}" exec -d companion bash -lc '
    source /opt/ros/humble/setup.bash
    rm -rf /tmp/leaderfollow_bag
    ros2 bag record -s mcap -o /tmp/leaderfollow_bag \
      /swarm/status /drone_0/mavros/local_position/pose \
      /drone_1/mavros/local_position/pose /drone_2/mavros/local_position/pose \
      /drone_3/mavros/local_position/pose /drone_4/mavros/local_position/pose
  '
fi

echo "==> /swarm/takeoff to 5 m (all drones)..."
companion "ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff '{altitude_m: 5.0}'" \
  | tee /tmp/lf_takeoff.txt
grep -q "success=True" /tmp/lf_takeoff.txt

echo "==> /swarm/follow_leader engage (diamond, 4 m)..."
companion "ros2 service call /swarm/follow_leader swarm_msgs/srv/FollowLeader \
  '{enable: true, formation_name: diamond, spacing_m: 4.0}'" \
  | tee /tmp/lf_engage.txt
grep -q "success=True" /tmp/lf_engage.txt

echo "==> Operator flies the leader — leg 1 (20 m East)..."
companion "ros2 service call /swarm/drone_0/manual_goto swarm_msgs/srv/ManualGoto \
  '{target: {x: 20.0, y: 0.0, z: 5.0}}'" | tee /tmp/lf_leg1.txt
grep -q "success=True" /tmp/lf_leg1.txt

echo "==> Operator flies the leader — leg 2 (20 m East, 18 m North)..."
companion "ros2 service call /swarm/drone_0/manual_goto swarm_msgs/srv/ManualGoto \
  '{target: {x: 20.0, y: 18.0, z: 5.0}}'" | tee /tmp/lf_leg2.txt
grep -q "success=True" /tmp/lf_leg2.txt

echo "==> Holding the diamond for ${HOLD_S} s while the followers settle..."
sleep "$HOLD_S"

echo "==> Checking follower drift (gate: <0.5 m mean)..."
"${COMPOSE[@]}" logs --no-color companion > /tmp/orynth_leaderfollow_full.log 2>&1 || true
mapfile -t drifts < <(
  grep -oP 'drift mean=\K[0-9.]+' /tmp/orynth_leaderfollow_full.log | tail -n 15
)
if [ "${#drifts[@]}" -lt 5 ]; then
  echo "ERROR: only ${#drifts[@]} drift samples — follow loop did not run" >&2
  exit 1
fi
worst="$(printf '%s\n' "${drifts[@]}" | sort -g | tail -n1)"
echo "==> worst settled drift over the last ${#drifts[@]} samples: ${worst} m"
awk -v w="$worst" 'BEGIN { exit (w < 0.5) ? 0 : 1 }' || {
  echo "FAIL: leader-follow drift ${worst} m exceeds the 0.5 m gate" >&2
  exit 1
}

echo "==> Exercising the leader-pose watchdog (simulated dropout)..."
companion "ros2 param set /swarm_server simulate_leader_dropout true"
sleep 6
"${COMPOSE[@]}" logs --no-color companion > /tmp/orynth_leaderfollow_full.log 2>&1 || true
if ! grep -qF "holding position (watchdog)" /tmp/orynth_leaderfollow_full.log; then
  echo "FAIL: watchdog did not engage on the simulated leader-pose dropout" >&2
  exit 1
fi
echo "==> Watchdog engaged — followers held position"
companion "ros2 param set /swarm_server simulate_leader_dropout false"
sleep 3

if [ "$RECORD" = "1" ]; then
  "${COMPOSE[@]}" exec -T companion pkill -INT -f "ros2 bag record" || true
  sleep 4
  mkdir -p "$REPO_ROOT/accept"
  bag="$(docker exec orynth-swarm-companion \
    bash -lc 'ls /tmp/leaderfollow_bag/*.mcap 2>/dev/null | head -n1' || true)"
  if [ -n "$bag" ]; then
    docker cp "orynth-swarm-companion:${bag}" \
      "$REPO_ROOT/accept/leaderfollow_sitl.mcap"
    echo "==> Wrote accept/leaderfollow_sitl.mcap"
  fi
fi

echo "==> /swarm/follow_leader disengage..."
companion "ros2 service call /swarm/follow_leader swarm_msgs/srv/FollowLeader \
  '{enable: false}'" | tee /tmp/lf_disengage.txt
grep -q "success=True" /tmp/lf_disengage.txt

echo "==> /swarm/land (all drones)..."
companion "ros2 service call /swarm/land std_srvs/srv/Trigger '{}'" \
  | tee /tmp/lf_land.txt
grep -q "success=True" /tmp/lf_land.txt

echo "==> Phase 2.5a leader-follow SITL gate PASS"
