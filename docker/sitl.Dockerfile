# syntax=docker/dockerfile:1.7
# ArduPilot SITL + Gazebo Harmonic + ardupilot_gazebo. amd64-only (no Jetson SITL).
ARG BASE_TAG=orynth-base:latest
FROM ${BASE_TAG}

ARG ARDUPILOT_REF=Copter-4.5.7
ARG ARDUPILOT_GZ_REF=main
ARG ARDUPILOT_GAZEBO_REF=main

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl gnupg lsb-release \
      wget software-properties-common \
    && curl -sSL https://packages.osrfoundation.org/gazebo.gpg \
        -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable jammy main" \
        > /etc/apt/sources.list.d/gazebo-stable.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        gz-harmonic \
        ros-${ROS_DISTRO}-ros-gzharmonic \
    && rm -rf /var/lib/apt/lists/*

# Build ArduPilot at the pinned tag.
RUN git clone --depth 1 --branch ${ARDUPILOT_REF} https://github.com/ArduPilot/ardupilot.git /ardupilot \
    && cd /ardupilot \
    && git submodule update --init --recursive \
    && Tools/environment_install/install-prereqs-ubuntu.sh -y \
    && ./waf configure --board sitl \
    && ./waf copter

ENV PATH="/ardupilot/build/sitl/bin:${PATH}"

# ardupilot_gazebo plugin (model + bridge).
RUN git clone https://github.com/ArduPilot/ardupilot_gazebo.git /opt/ardupilot_gazebo \
    && cd /opt/ardupilot_gazebo \
    && git checkout ${ARDUPILOT_GAZEBO_REF} \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release \
    && make -j$(nproc)

ENV GZ_SIM_SYSTEM_PLUGIN_PATH=/opt/ardupilot_gazebo/build \
    GZ_SIM_RESOURCE_PATH=/opt/ardupilot_gazebo/models:/opt/ardupilot_gazebo/worlds
