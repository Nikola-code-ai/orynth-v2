cmake_minimum_required(VERSION 3.16)
project(swarm_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY launch config worlds
  DESTINATION share/${PROJECT_NAME}
  OPTIONAL
)

ament_package()
