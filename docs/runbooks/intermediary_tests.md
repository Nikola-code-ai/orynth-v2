# Intermediary Swarm Testing

Jumping straight into a full 5-drone hardware flight can be overwhelming. The Orynth swarm orchestrator (`swarm_server`) is designed to automatically scale its logic based on the `DRONE_COUNT` environment variable. 

By setting this variable, you can safely perform intermediary steps to test your ground control setup, network, and MAVROS links with just 1 or 2 drones before adding the rest.

---

## 1. Single Drone Test (Leader Only)

**Goal:** Verify the Ground Control Station (GCS) connects to the Leader Drone (`drone_0`), Foxglove receives ROS 2 telemetry, and you can arm/takeoff a single Jetson via the companion computer.

**On the Leader Jetson (`drone_0`):**
```bash
cd ~/orynth-v2/v2
export DRONE_COUNT=1
export CYCLONEDDS_URI=file:///workspace/config/networks/cyclonedds_drone_0.xml
bash scripts/bringup/demo_swarm.sh up 0
```

**Preflight Gate (Run on the Leader):**
```bash
export DRONE_COUNT=1
bash scripts/bringup/demo_swarm.sh preflight
```
*(Because `DRONE_COUNT=1`, it will only poll `drone_0` for GPS/EKF lock and Battery levels, then immediately pass).*

**Test the Swarm Commands:**
1. Connect Foxglove to `ws://<leader-ip>:8765` and verify you see the pose.
2. Ensure the safety pilot is ready, then command a takeoff:
   ```bash
   docker exec -it orynth-demo-0 bash -lc 'source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash; ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff "{altitude_m: 5.0}"'
   ```
3. Command a landing:
   ```bash
   docker exec -it orynth-demo-0 bash -lc 'source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash; ros2 service call /swarm/land std_srvs/srv/Trigger "{}"'
   ```

---

## 2. Two Drone Test (Leader + 1 Follower)

**Goal:** Verify Cyclone DDS is routing traffic properly between two separate Jetsons over your WiFi Access Point, and test the core `follow_leader` logic in the air.

**On the Leader Jetson (`drone_0`):**
```bash
cd ~/orynth-v2/v2
export DRONE_COUNT=2
export CYCLONEDDS_URI=file:///workspace/config/networks/cyclonedds_drone_0.xml
bash scripts/bringup/demo_swarm.sh up 0
```

**On the Follower Jetson (`drone_1`):**
```bash
cd ~/orynth-v2/v2
export DRONE_COUNT=2
export CYCLONEDDS_URI=file:///workspace/config/networks/cyclonedds_drone_1.xml
bash scripts/bringup/demo_swarm.sh up 1
```

**Preflight Gate (Run on the Leader):**
```bash
export DRONE_COUNT=2
bash scripts/bringup/demo_swarm.sh preflight
```
*(It will now wait for both `drone_0` and `drone_1` to pass health checks).*

**Test the Leader-Follow Logic:**
1. Command a takeoff for both:
   ```bash
   docker exec -it orynth-demo-0 bash -lc 'source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash; ros2 service call /swarm/takeoff swarm_msgs/srv/SwarmTakeoff "{altitude_m: 5.0}"'
   ```
2. The Safety Pilot on `drone_0` switches the Leader into `LOITER` mode (taking manual RC control).
3. Engage the leader-follow loop:
   ```bash
   docker exec -it orynth-demo-0 bash -lc 'source /opt/ros/humble/setup.bash; source /opt/overlay/setup.bash; ros2 service call /swarm/follow_leader swarm_msgs/srv/FollowLeader "{enable: true, formation_name: diamond, spacing_m: 6.0}"'
   ```
4. As the Safety Pilot manually flies the leader around the field, `drone_1` will autonomously follow its live pose, maintaining a 6-meter distance.
5. Disable `follow_leader`, then call `/swarm/land` to bring both down.

---

Once you are comfortable with these intermediary steps and your networking is proven solid, testing the full 5-drone setup simply involves adding `drone_2` through `drone_4` and omitting the `DRONE_COUNT` override (as it defaults to 5).
