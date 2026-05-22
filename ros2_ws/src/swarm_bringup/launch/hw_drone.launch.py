"""Single-drone HARDWARE bringup for the leader-follow demo — Phase 2.5b.

Each Jetson Nano runs exactly one drone. This launch brings up that drone's
ROS side against the real ArduPilot flight controller wired to the Jetson:

* one MAVROS instance, pushed into ``/drone_<DRONE_ID>`` so its topics land at
  ``/drone_<DRONE_ID>/mavros/*`` — the namespace ``MavrosAdapter`` expects —
  with a distinct ``tgt_system`` (``DRONE_ID + 1``) for a unique ``/uas``
  router prefix (matches the FC's ``SYSID_THISMAV``);
* on the **leader's** Jetson only (``WITH_SWARM_SERVER=1``): the Foxglove
  bridge and ``swarm_server_node`` — the orchestrator that drives all five
  drones over the shared Cyclone DDS LAN.

Followers run MAVROS alone; the leader's Jetson is the demo's ground hub.
Everything is environment-driven so ``docker/compose.demo.yaml`` configures it;
it also runs directly for bench bring-up:

    DRONE_ID=0 WITH_SWARM_SERVER=1 DRONE_COUNT=5 \\
        ros2 launch swarm_bringup hw_drone.launch.py
"""

import os

from launch import LaunchDescription
from launch.actions import GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node, PushRosNamespace
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    drone_id = int(os.environ.get("DRONE_ID", "0"))
    drone_count = int(os.environ.get("DRONE_COUNT", "5"))
    # ArduPilot TELEM ports default to 57600 baud; raise SERIALx_BAUD and this
    # to 921600 for the formation telemetry rates.
    fcu_url = os.environ.get("FCU_URL", "serial:///dev/ttyTHS1:57600")
    foxglove_port = os.environ.get("FOXGLOVE_PORT", "8765")
    with_server = os.environ.get("WITH_SWARM_SERVER", "0") == "1"
    leader_timeout = float(os.environ.get("LEADER_POSE_TIMEOUT", "1.5"))
    # Real airframes fly in one shared sky — no per-slot altitude stagger; the
    # formation is flat and physical spacing keeps the drones apart.
    alt_step = float(os.environ.get("FORMATION_ALT_STEP", "0.0"))

    apm_launch = PathJoinSubstitution(
        [FindPackageShare("mavros"), "launch", "apm.launch"]
    )

    # This drone's MAVROS, namespaced /drone_<id> with a distinct tgt_system.
    mavros = GroupAction(
        [
            PushRosNamespace(f"drone_{drone_id}"),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(apm_launch),
                launch_arguments={
                    "fcu_url": fcu_url,
                    "tgt_system": str(drone_id + 1),
                    "tgt_component": "1",
                }.items(),
            ),
        ]
    )

    entities = [mavros]

    # The leader's Jetson is the demo ground hub: it also runs the Foxglove
    # bridge (one bridge sees the whole DDS LAN) and the swarm orchestrator.
    if with_server:
        entities.append(
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(
                    PathJoinSubstitution(
                        [
                            FindPackageShare("foxglove_bridge"),
                            "launch",
                            "foxglove_bridge_launch.xml",
                        ]
                    )
                ),
                launch_arguments={"port": foxglove_port}.items(),
            )
        )
        entities.append(
            Node(
                package="swarm_control",
                executable="swarm_server",
                name="swarm_server",
                output="screen",
                parameters=[
                    {
                        "drone_count": drone_count,
                        "mavros_ns_prefix": "drone_",
                        "formation_alt_step_m": alt_step,
                        "leader_pose_timeout_s": leader_timeout,
                    }
                ],
            )
        )

    return LaunchDescription(entities)
