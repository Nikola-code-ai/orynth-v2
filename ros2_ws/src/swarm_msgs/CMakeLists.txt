cmake_minimum_required(VERSION 3.16)
project(swarm_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  msg/DroneState.msg
  msg/SwarmStatus.msg
  msg/DetectionWithGeo.msg
  srv/SetFormation.srv
  srv/SwarmTakeoff.srv
  srv/ManualGoto.srv
  srv/FollowLeader.srv
  srv/AssignSearchArea.srv
  action/FlySwarmMission.action
  action/SearchArea.action
  DEPENDENCIES std_msgs geometry_msgs sensor_msgs builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
