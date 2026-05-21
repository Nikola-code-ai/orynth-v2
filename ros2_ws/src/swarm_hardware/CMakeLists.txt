cmake_minimum_required(VERSION 3.16)
project(swarm_hardware)
find_package(ament_cmake REQUIRED)

# Hardware-only package — only build on arm64 (Jetson) or when explicitly requested.
if(NOT (CMAKE_SYSTEM_PROCESSOR STREQUAL "aarch64" OR DEFINED ENV{SWARM_BUILD_HARDWARE}))
  message(STATUS "swarm_hardware: skipping build on non-aarch64 host. Set SWARM_BUILD_HARDWARE=1 to override.")
  ament_package()
  return()
endif()

install(DIRECTORY launch config udev DESTINATION share/${PROJECT_NAME} OPTIONAL)
ament_package()
