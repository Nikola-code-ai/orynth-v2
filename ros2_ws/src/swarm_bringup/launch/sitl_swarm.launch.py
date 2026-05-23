"""Five-drone SITL swarm bringup — Phase 2 deliverable (PLAN section D).

Brings up the ROS side of the swarm dev stack against N already-running
ArduPilot SITL instances (see ``swarm_sim/sitl_launcher.py``):

* N namespaced MAVROS instances (``drone_0``..``drone_<N-1>``), each bridging
  one SITL over ``tcp://<sim_host>:<5760 + 10*i>``;
* the Foxglove bridge for the ``operator.json`` layout;
* ``swarm_server_node`` — the five-drone orchestrator.

Each drone gets a **distinct** ``tgt_system`` (``i + 1``). MAVROS derives its
internal ``/uas<id>`` router prefix from ``tgt_system``; a shared id collides
across instances and silently kills one. ``tgt_system`` must therefore match
the SITL ``SYSID_THISMAV`` (``i + 1``) that ``sitl_launcher.py`` assigns —
PLAN section G's per-instance SYSID mitigation.

Counts and hosts come from the environment so ``docker/compose.swarm.yaml``
drives it; it also runs directly for non-Docker development:

    DRONE_COUNT=5 SIM_HOST=127.0.0.1 ros2 launch swarm_bringup sitl_swarm.launch.py
"""

import os

from launch import LaunchDescription
from launch.actions import GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node, PushRosNamespace
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    drone_count = int(os.environ.get("DRONE_COUNT", "5"))
    sim_host = os.environ.get("SIM_HOST", "sim")
    base_port = int(os.environ.get("MAVROS_BASE_PORT", "5760"))
    foxglove_port = os.environ.get("FOXGLOVE_PORT", "8765")
    alt_step = float(os.environ.get("FORMATION_ALT_STEP", "0.0"))
    leader_timeout = float(os.environ.get("LEADER_POSE_TIMEOUT", "1.5"))
    lock_heading = os.environ.get("FORMATION_LOCK_HEADING", "0").lower() in (
        "1",
        "true",
        "yes",
    )

    apm_launch = PathJoinSubstitution(
        [FindPackageShare("mavros"), "launch", "apm.launch"]
    )

    # One MAVROS per drone, each pushed into its own /drone_<i> namespace so
    # topics land at /drone_<i>/mavros/* — the namespace MavrosAdapter expects
    # — and each with a distinct tgt_system (i + 1) for a unique /uas prefix.
    mavros_group = []
    for i in range(drone_count):
        fcu_url = f"tcp://{sim_host}:{base_port + 10 * i}@"
        mavros_group.append(
            GroupAction(
                [
                    PushRosNamespace(f"drone_{i}"),
                    IncludeLaunchDescription(
                        AnyLaunchDescriptionSource(apm_launch),
                        launch_arguments={
                            "fcu_url": fcu_url,
                            "tgt_system": str(i + 1),
                            "tgt_component": "1",
                        }.items(),
                    ),
                ]
            )
        )

    foxglove = IncludeLaunchDescription(
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

    swarm_server = Node(
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
                "formation_lock_heading": lock_heading,
            }
        ],
    )

    return LaunchDescription([*mavros_group, foxglove, swarm_server])
