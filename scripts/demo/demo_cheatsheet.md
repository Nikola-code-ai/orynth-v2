# Orynth v2 swarm demo — operator cheatsheet

Paste these into the **commands** pane (bottom-right of the tmux grid). The `sw` alias is preloaded by `presentation_demo.sh up` — it wraps every ros2 call in a `docker compose exec` against the companion container with the ROS overlay sourced.

> Mirrors the proven sequence from `scripts/bringup/sitl_swarm.sh` (Phase 2 nightly acceptance gate).

---

## 0. Pre-flight — confirm the orchestrator is alive

```bash
sw ros2 service list | grep /swarm
```

Expect to see `/swarm/takeoff`, `/swarm/engage_formation`, `/swarm/follow_leader`, `/swarm/land`.

```bash
sw ros2 topic list | grep -c '/drone_'
```

Expect a count of ~50–60 (≥ 10 topics × 5 drones).

---

## 1. Coordinated takeoff to 5 m

```bash
sw ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff "{altitude_m: 5.0}"
```

Watch:
- **Gazebo window** — all 5 drones lift simultaneously.
- **drone_0..drone_4 panes** — `z` field climbs from ~0 to ~5.
- **/swarm/status pane** — `mission_phase` flips to `"takeoff"` then `"hover"`.

---

## 2. Engage diamond formation (4 m spacing)

```bash
sw ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation \
  "{formation_name: diamond, spacing_m: 4.0, heading_deg: 0.0}"
```

Watch:
- **Gazebo** — drones slide into a diamond around drone_0.
- **/swarm/formation_error pane** — values converge toward zero (< 0.5 m mean is the acceptance gate).
- **/swarm/status pane** — `formation: "diamond"`, `mission_phase: "engage_formation"`.

Hold here for screenshots / audience time.

---

## 3. (Optional) Other formations to show off

```bash
sw ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation "{formation_name: vee,     spacing_m: 4.0, heading_deg: 0.0}"
sw ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation "{formation_name: line,    spacing_m: 4.0, heading_deg: 0.0}"
sw ros2 service call /swarm/engage_formation swarm_msgs/srv/SetFormation "{formation_name: column,  spacing_m: 4.0, heading_deg: 0.0}"
```

---

## 4. Coordinated landing

```bash
sw ros2 service call /swarm/land std_srvs/srv/Trigger "{}"
```

Watch z values descend to 0; `mission_phase` flips to `"land"`.

---

## 5. Teardown

```bash
# Kill the tmux grid (leaves the stack running, in case you want to re-demo)
bash scripts/demo/presentation_demo.sh down

# Tear down the swarm stack
make swarm-down
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| A pose pane shows nothing | The stack isn't fully up yet — wait for `docker inspect --format='{{.State.Health.Status}}' orynth-swarm-companion` to read `healthy`, then relaunch the grid. |
| `/swarm/formation_error` empty | Engage formation first (step 2); the topic publishes only while a formation is active. |
| Gazebo window didn't open | `xhost +local:root` (already attempted by `make swarm-up`), then `make swarm-down && DRONE_COUNT=5 make swarm-up`. Confirm `echo $DISPLAY` returns `:1`. |
| Pane title cut off | Widen the terminal window before attaching — the grid is sized for ≥ 200 columns. |
