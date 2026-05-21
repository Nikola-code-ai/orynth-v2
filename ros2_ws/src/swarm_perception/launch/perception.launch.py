"""Perception bringup. Phase 0 launches only the passthrough YOLO node."""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            Node(
                package="swarm_perception",
                executable="yolo_detector",
                name="yolo_detector",
                output="screen",
                emulate_tty=True,
                parameters=[{"use_sim_time": True}],
            ),
        ]
    )
