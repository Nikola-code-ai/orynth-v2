#!/usr/bin/env bash
# Multi-terminal tmux showcase for the 5-drone SITL swarm.
# Pairs with `make swarm-up` (Gazebo GUI on screen) and the cheatsheet next to
# this file. See /home/nikola/.claude/plans/i-need-to-showcase-zazzy-rain.md
# for the design.

set -euo pipefail

SESSION="orynth_demo"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPANION="orynth-swarm-companion"   # container name (plain `docker exec` target)
DRONE_COUNT="${DRONE_COUNT:-5}"
CHEATSHEET="$REPO_ROOT/scripts/demo/demo_cheatsheet.md"

# ros2 invocation inside the companion container, overlay sourced.
ROS_PREFIX='source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash;'

usage() {
  cat <<EOF
Usage: $0 {up|down|attach}

  up      Build the tmux grid against the running swarm stack.
  down    Kill the tmux session (leaves the swarm stack alone).
  attach  tmux attach -t $SESSION

Prereqs for 'up': tmux installed, and 'make swarm-up' already healthy
(see: docker inspect --format='{{.State.Health.Status}}' $COMPANION).
EOF
}

require_tmux() {
  command -v tmux >/dev/null 2>&1 || {
    echo "tmux is not installed. Run: sudo apt install -y tmux" >&2
    exit 1
  }
}

require_companion_healthy() {
  local status
  status="$(docker inspect --format='{{.State.Health.Status}}' "$COMPANION" 2>/dev/null || echo missing)"
  if [[ "$status" != "healthy" ]]; then
    echo "Companion container is '$status' (need 'healthy')." >&2
    echo "Bring up the stack first: DRONE_COUNT=$DRONE_COUNT make swarm-up" >&2
    exit 1
  fi
}

# Compose a `docker exec` invocation that runs $1 inside the companion with
# ROS env sourced. Returned as a single string suitable for `send-keys`.
exec_in_companion() {
  local inner="$1"
  printf "%q " docker exec "$COMPANION" bash -lc "$ROS_PREFIX $inner"
}

pane_echo() {
  local target="$1" title="$2" cmd="$3"
  tmux select-pane -t "$target" -T "$title"
  tmux send-keys   -t "$target" "$cmd" C-m
}

case "${1:-}" in
  up)
    require_tmux
    require_companion_healthy

    # Idempotent: nuke any prior session.
    tmux kill-session -t "$SESSION" 2>/dev/null || true

    # Start with a single pane and force a roomy virtual size so the splits
    # render predictably even before the operator attaches.
    tmux new-session -d -s "$SESSION" -n swarm -x 240 -y 60

    # Pane border titles for screenshot clarity.
    tmux set-option -t "$SESSION" -g pane-border-status top
    tmux set-option -t "$SESSION" -g pane-border-format ' #{pane_title} '
    tmux set-option -t "$SESSION" -g status-left  '[ #S ] '
    tmux set-option -t "$SESSION" -g status-right ' Orynth v2 — 5-drone SITL swarm | Gazebo on :1 '

    # Build the 8-pane grid using STABLE pane IDs (e.g. %12). Pane indices
    # like .0/.1/.2 renumber on every split, so we capture each new pane's ID
    # via `-P -F` and target by ID for the rest of the build. Virtual window
    # is 240 cols × 60 rows (set above).

    # Initial pane ID (the one new-session created).
    TOP_LEFT=$(tmux list-panes -t "$SESSION" -F '#{pane_id}' | head -1)

    # Split off the bottom row (15 rows tall).
    BOTTOM_LEFT=$(tmux split-window -v -t "$TOP_LEFT" -l 15 -P -F '#{pane_id}')
    # Now split the (current) top section to peel off a middle row (22 rows).
    MIDDLE_LEFT=$(tmux split-window -v -t "$TOP_LEFT" -l 22 -P -F '#{pane_id}')

    # Top row → 3 columns (LTR: TOP_LEFT | TOP_MID | TOP_RIGHT).
    TOP_RIGHT=$(tmux split-window -h -t "$TOP_LEFT" -l 80 -P -F '#{pane_id}')
    TOP_MID=$(  tmux split-window -h -t "$TOP_LEFT" -l 79 -P -F '#{pane_id}')

    # Middle row → 3 columns (LTR: MIDDLE_LEFT | MIDDLE_MID | MIDDLE_RIGHT).
    MIDDLE_RIGHT=$(tmux split-window -h -t "$MIDDLE_LEFT" -l 80 -P -F '#{pane_id}')
    MIDDLE_MID=$(  tmux split-window -h -t "$MIDDLE_LEFT" -l 79 -P -F '#{pane_id}')

    # Bottom row → 2 columns (formation_error wide | commands).
    BOTTOM_RIGHT=$(tmux split-window -h -t "$BOTTOM_LEFT" -l 69 -P -F '#{pane_id}')

    # Drone slot assignments.
    declare -A DRONE_PANE=(
      [0]="$TOP_LEFT"  [1]="$TOP_MID"  [2]="$TOP_RIGHT"
      [3]="$MIDDLE_LEFT" [4]="$MIDDLE_MID"
    )
    STATUS_PANE="$MIDDLE_RIGHT"
    FORMATION_PANE="$BOTTOM_LEFT"
    COMMANDS_PANE="$BOTTOM_RIGHT"

    for i in 0 1 2 3 4; do
      pane="${DRONE_PANE[$i]:-}"
      [[ -z "$pane" ]] && continue
      cmd="$(exec_in_companion "ros2 topic echo /drone_${i}/mavros/local_position/pose --no-arr")"
      pane_echo "$pane" "drone_${i}  ·  local_position/pose" "$cmd"
    done

    # Swarm-wide status (formation, mission_phase, per-drone state).
    pane_echo "$STATUS_PANE" "/swarm/status" \
      "$(exec_in_companion "ros2 topic echo /swarm/status --no-arr")"

    # Formation tracking error (per-follower convergence).
    pane_echo "$FORMATION_PANE" "/swarm/formation_error  ·  follower drift (m)" \
      "$(exec_in_companion "ros2 topic echo /swarm/formation_error")"

    # Operator commands. Plain bash with a banner pointing at the cheatsheet
    # — no auto-execute, the speaker drives this pane live.
    CMDP="$COMMANDS_PANE"
    tmux select-pane -t "$CMDP" -T "commands  ·  paste from demo_cheatsheet.md"
    tmux send-keys -t "$CMDP" "clear; cat <<'BANNER'
─────────────────────────────────────────────────
 Orynth v2 swarm demo — operator pane
 Cheatsheet: $CHEATSHEET
 Container : $COMPANION
─────────────────────────────────────────────────
BANNER" C-m

    # Shorthand wrapper: 'sw <ros2 cmd>' runs inside the companion container.
    tmux send-keys -t "$CMDP" \
      "sw() { docker exec $COMPANION bash -lc \"$ROS_PREFIX \$*\"; }" C-m
    tmux send-keys -t "$CMDP" "echo; echo 'Try:  sw ros2 service list \\| grep /swarm'" C-m

    tmux select-pane -t "$CMDP"
    echo "Demo grid ready. Attach with:  tmux attach -t $SESSION"
    ;;

  down)
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "killed session $SESSION" || \
      echo "no session named $SESSION"
    ;;

  attach)
    require_tmux
    exec tmux attach -t "$SESSION"
    ;;

  *)
    usage
    exit 1
    ;;
esac
