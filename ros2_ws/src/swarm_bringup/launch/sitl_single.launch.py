"""Single-drone SITL bringup — Phase 1 deliverable (PLAN section D).

Brings up the ROS side of the single-drone dev stack against an
already-running ArduPilot SITL instance:

* MAVROS (ArduPilot/APM profile) bridging MAVLink <-> ROS 2;
* the Foxglove bridge for live visualization.

Used by ``docker/compose.dev.yaml`` (companion service) and runnable directly
for non-Docker development:

    ros2 launch swarm_bringup sitl_single.launch.py fcu_url:=tcp://127.0.0.1:5760@
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    fcu_url = LaunchConfiguration("fcu_url")
    tgt_system = LaunchConfiguration("tgt_system")
    foxglove_port = LaunchConfiguration("foxglove_port")

    mavros = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare("mavros"), "launch", "apm.launch"]
            )
        ),
        launch_arguments={
            "fcu_url": fcu_url,
            "tgt_system": tgt_system,
            "tgt_component": "1",
        }.items(),
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

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "fcu_url",
                default_value="tcp://127.0.0.1:5760@",
                description="MAVLink endpoint of the ArduPilot SITL instance.",
            ),
            DeclareLaunchArgument(
                "tgt_system",
                default_value="1",
                description="Target MAVLink system id.",
            ),
            DeclareLaunchArgument(
                "foxglove_port",
                default_value="8765",
                description="WebSocket port for the Foxglove bridge.",
            ),
            mavros,
            foxglove,
        ]
    )
