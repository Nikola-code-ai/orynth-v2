#!/usr/bin/env bash
# Phase 2.5b — leader-follow hardware demo bringup (PLAN section D).
#
# Operator-facing wrapper around docker/compose.demo.yaml. One Jetson Nano runs
# one drone; the leader's Jetson (drone_0) also hosts the swarm orchestrator.
#
#   demo_swarm.sh up   <DRONE_ID>   bring this Jetson up; --wait blocks until
#                                   its MAVROS<->FC link is live (ID 0 = leader)
#   demo_swarm.sh preflight         swarm-wide health gate — run on the leader
#                                   once every Jetson is up; blocks until the
#                                   leader and all followers report a live FC
#                                   link, EKF global origin, and battery >90%
#   demo_swarm.sh down  <DRONE_ID>  tear this Jetson's stack down
#
# Typical demo sequence (leader first, then each follower):
#   drone_0 Jetson:  demo_swarm.sh up 0
#   drone_1 Jetson:  demo_swarm.sh up 1      ... drone_2..4 likewise
#   drone_0 Jetson:  demo_swarm.sh preflight
# A green preflight clears the swarm for the first_flight.md flight checklist.
#
# Env: DRONE_COUNT (default 5), BATTERY_MIN (0.90), PREFLIGHT_TIMEOUT (240 s).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=(docker compose -f docker/compose.demo.yaml)
DRONE_COUNT="${DRONE_COUNT:-5}"
BATTERY_MIN="${BATTERY_MIN:-0.90}"
PREFLIGHT_TIMEOUT="${PREFLIGHT_TIMEOUT:-240}"

die() { echo "ERROR: $*" >&2; exit 1; }

usage() {
  sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# Run a ROS 2 command inside the leader's container, both overlays sourced.
leader_exec() {
  docker exec orynth-demo-0 bash -lc \
    "source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash; $*"
}

cmd_up() {
  local id="${1:-}"
  [[ "$id" =~ ^[0-9]+$ ]] || die "up needs a numeric DRONE_ID (0..$((DRONE_COUNT - 1)))"
  export DRONE_ID="$id"
  export DRONE_COUNT
  if [ "$id" -eq 0 ]; then
    export WITH_SWARM_SERVER=1
    echo "==> Bringing up drone_0 (LEADER — also runs Foxglove + swarm_server)"
  else
    export WITH_SWARM_SERVER=0
    echo "==> Bringing up drone_${id} (follower)"
  fi
  # --wait blocks on the healthcheck: healthy == MAVROS has a live FC link.
  "${COMPOSE[@]}" up -d --build --wait --wait-timeout 360
  echo "==> drone_${id} up — MAVROS <-> flight-controller link is live"
  [ "$id" -eq 0 ] && echo "    Foxglove bridge: ws://<this-jetson-ip>:8765"
}

cmd_down() {
  local id="${1:-0}"
  export DRONE_ID="$id"
  "${COMPOSE[@]}" down -v --remove-orphans
  echo "==> drone_${id} stack down"
}

# Health of one drone: live FC link + EKF global origin + battery over the gate.
check_drone() {
  local n="$1" ns="/drone_$1/mavros"
  local state lat pct
  state="$(leader_exec "timeout 7 ros2 topic echo --once ${ns}/state" 2>/dev/null || true)"
  grep -iqE 'connected:[[:space:]]*true' <<<"$state" || { echo "link down"; return 1; }
  lat="$(leader_exec "timeout 7 ros2 topic echo --once --field latitude ${ns}/global_position/global" 2>/dev/null || true)"
  [ -n "${lat//[$' \t\r\n']/}" ] || { echo "no EKF global origin / GPS"; return 1; }
  pct="$(leader_exec "timeout 7 ros2 topic echo --once --field percentage ${ns}/battery" 2>/dev/null || true)"
  pct="${pct//[$' \t\r\n']/}"
  [ -n "$pct" ] || { echo "no battery telemetry"; return 1; }
  awk -v p="$pct" -v m="$BATTERY_MIN" 'BEGIN { exit (p >= m) ? 0 : 1 }' \
    || { echo "battery $(awk -v p="$pct" 'BEGIN{printf "%.0f%%", p*100}') < gate"; return 1; }
  echo "OK (battery $(awk -v p="$pct" 'BEGIN{printf "%.0f%%", p*100}'))"
  return 0
}

cmd_preflight() {
  docker ps --format '{{.Names}}' | grep -qx orynth-demo-0 \
    || die "leader container orynth-demo-0 not running — 'demo_swarm.sh up 0' first"
  echo "==> Swarm preflight gate — ${DRONE_COUNT} drones, battery >= $(awk -v m="$BATTERY_MIN" 'BEGIN{printf "%.0f%%", m*100}')"
  local deadline=$(( $(date +%s) + PREFLIGHT_TIMEOUT ))
  while :; do
    local all_ok=1 line
    for ((n = 0; n < DRONE_COUNT; n++)); do
      if line="$(check_drone "$n")"; then
        printf '  drone_%d: %s\n' "$n" "$line"
      else
        printf '  drone_%d: NOT READY — %s\n' "$n" "$line"
        all_ok=0
      fi
    done
    if [ "$all_ok" -eq 1 ]; then
      echo "==> PREFLIGHT PASS — all ${DRONE_COUNT} drones ready for the demo"
      echo "    Proceed with docs/runbooks/first_flight.md."
      return 0
    fi
    [ "$(date +%s)" -ge "$deadline" ] \
      && die "preflight timed out after ${PREFLIGHT_TIMEOUT}s — drones not all ready"
    echo "    ... retrying in 10 s"
    sleep 10
  done
}

case "${1:-}" in
  up)        shift; cmd_up "$@" ;;
  down)      shift; cmd_down "$@" ;;
  preflight) cmd_preflight ;;
  -h|--help|help|"") usage 0 ;;
  *)         die "unknown subcommand '$1' (try: up | preflight | down)" ;;
esac
