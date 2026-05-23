"""Single-drone HARDWARE bringup for the leader-follow demo — Phase 2.5b.

Each Jetson Nano runs exactly one drone. This launch brings up that drone's
ROS side against the real ArduPilot flight controller wired to the Jetson:

* one MAVROS instance, pushed into ``/drone_<DRONE_ID>`` so its topics land at
  ``/drone_<DRONE_ID>/mavros/*`` — the namespace ``MavrosAdapter`` expects —
  with a distinct ``tgt_system`` (``DRONE_ID + 1``) for a unique ``/uas``
  router prefix (matches the FC's ``SYSID_THISMAV``);
* one ``radio_bridge`` instance (package ``swarm_radio``) wired to the SiK /
  RFD900 radio. The bridge is the inter-drone transport: it replaces what
  Cyclone DDS over WiFi used to do for cross-Jetson topics (ADR 0009);
* on the **leader's** Jetson only (``WITH_SWARM_SERVER=1``): the Foxglove
  bridge and ``swarm_server_node`` — the orchestrator that drives all drones
  via the local ``/drone_K/mavros/*`` surface (real for drone 0, synthesised
  by the leader-side ``radio_bridge`` for drone 1..N).

Followers run MAVROS + radio_bridge alone; the leader's Jetson additionally
runs swarm_server + Foxglove. Each Jetson now uses its OWN ``ROS_DOMAIN_ID``
(``100 + DRONE_ID``) — there is no longer a shared DDS LAN across drones.

Everything is environment-driven so ``docker/compose.demo.yaml`` configures
it; it also runs directly for bench bring-up:

    DRONE_ID=0 WITH_SWARM_SERVER=1 DRONE_COUNT=2 RADIO_ROLE=leader \\
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
    drone_count = int(os.environ.get("DRONE_COUNT", "2"))
    # ArduPilot TELEM ports default to 57600 baud; raise SERIALx_BAUD and this
    # default to 921600 baud on real hardware to avoid stream choking.
    fcu_url = os.environ.get("FCU_URL", "serial:///dev/ttyTHS1:921600")
    foxglove_port = os.environ.get("FOXGLOVE_PORT", "8765")
    with_server = os.environ.get("WITH_SWARM_SERVER", "0") == "1"
    leader_timeout = float(os.environ.get("LEADER_POSE_TIMEOUT", "1.5"))
    # Real airframes fly in one shared sky — no per-slot altitude stagger; the
    # formation is flat and physical spacing keeps the drones apart.
    alt_step = float(os.environ.get("FORMATION_ALT_STEP", "0.0"))
    # Lock the formation's heading to engage-time so the diamond translates
    # with the leader but never rotates around it. Stops followers swinging
    # through the leader when ArduPilot's WP_YAW_BEHAVIOR points the leader's
    # nose at each new goto target.
    lock_heading = os.environ.get("FORMATION_LOCK_HEADING", "0").lower() in (
        "1",
        "true",
        "yes",
    )

    # Radio bridge config — see swarm_radio.radio_bridge_node.
    radio_role = os.environ.get("RADIO_ROLE", "leader" if with_server else "follower")
    radio_device = os.environ.get("RADIO_DEVICE", "/dev/ttyUSB_RFD")
    radio_baud = int(os.environ.get("RADIO_BAUD", "57600"))

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

    radio_bridge = Node(
        package="swarm_radio",
        executable="radio_bridge",
        name="radio_bridge",
        output="screen",
        parameters=[
            {
                "role": radio_role,
                "local_drone_id": drone_id,
                "drone_count": drone_count,
                "serial_device": radio_device,
                "serial_baud": radio_baud,
            }
        ],
    )

    entities = [mavros, radio_bridge]

    # The leader's Jetson is the demo ground hub: it also runs the Foxglove
    # bridge and the swarm orchestrator. swarm_server's MavrosAdapter for each
    # follower drone N talks to /drone_N/mavros/* — those topics are now
    # synthesised locally by radio_bridge (role=leader) from radio frames.
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
                        "formation_lock_heading": lock_heading,
                    }
                ],
            )
        )

    return LaunchDescription(entities)
