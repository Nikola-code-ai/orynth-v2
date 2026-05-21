cmake_minimum_required(VERSION 3.16)
project(swarm_behaviors)

# Phase 0 scaffold: no C++ sources yet. BehaviorTree.CPP plugins and the
# rclcpp/rclcpp_action/mavros_msgs find_package calls land in Phase 5 when the
# search-and-rescue tree is implemented. Keeping them REQUIRED now would fail
# the build against deps nothing consumes.
find_package(ament_cmake REQUIRED)

install(DIRECTORY trees plugins
  DESTINATION share/${PROJECT_NAME}
  OPTIONAL
)

ament_package()
