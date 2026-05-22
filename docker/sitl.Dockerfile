# syntax=docker/dockerfile:1.7
# ArduPilot SITL + Gazebo Harmonic + ardupilot_gazebo. amd64-only (no Jetson SITL).
ARG BASE_TAG=orynth-base:latest
FROM ${BASE_TAG}

# Pinned per ADR 0007. ardupilot is a release tag; ardupilot_gazebo is the
# SHA mirrored in orynth.repos (refresh both via scripts/build/refresh_pins.sh).
ARG ARDUPILOT_REF=Copter-4.5.7
ARG ARDUPILOT_GAZEBO_REF=082a0fe231f6e63bc8d1598f1cba461d9e2ea7f5

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

# Build ArduPilot at the pinned tag. ArduPilot's prereq installer refuses to
# run as root, so the SITL binaries are built as a dedicated user with
# passwordless sudo; the resulting arducopter binary is world-executable and
# runs fine under the container's root user.
RUN apt-get update && apt-get install -y --no-install-recommends sudo \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash apbuild \
    && echo 'apbuild ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/apbuild \
    && chmod 0440 /etc/sudoers.d/apbuild

USER apbuild
WORKDIR /home/apbuild
# install-prereqs-ubuntu.sh needs $USER / $HOME, which Docker does not set for
# a non-root RUN — export them for this layer only.
RUN export HOME=/home/apbuild USER=apbuild \
    && git clone --depth 1 --branch ${ARDUPILOT_REF} \
        https://github.com/ArduPilot/ardupilot.git ardupilot \
    && cd ardupilot \
    && git submodule update --init --recursive \
    && Tools/environment_install/install-prereqs-ubuntu.sh -y \
    && ./waf configure --board sitl \
    && ./waf copter

USER root
WORKDIR /
ENV PATH="/home/apbuild/ardupilot/build/sitl/bin:${PATH}"

# ardupilot_gazebo build + runtime prerequisites (per its README). RapidJSON
# and OpenCV are find_package(REQUIRED); GStreamer is pkg_check_modules(REQUIRED)
# for the camera-streaming plugin. Kept in its own layer after the slow
# ArduPilot build so editing this list never invalidates that build's cache.
RUN apt-get update && apt-get install -y --no-install-recommends \
        rapidjson-dev \
        libopencv-dev \
        libgstreamer1.0-dev \
        libgstreamer-plugins-base1.0-dev \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-libav \
        gstreamer1.0-gl \
    && rm -rf /var/lib/apt/lists/*

# ardupilot_gazebo plugin (model + bridge).
RUN git clone https://github.com/ArduPilot/ardupilot_gazebo.git /opt/ardupilot_gazebo \
    && cd /opt/ardupilot_gazebo \
    && git checkout ${ARDUPILOT_GAZEBO_REF} \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release \
    && make -j$(nproc)

ENV GZ_SIM_SYSTEM_PLUGIN_PATH=/opt/ardupilot_gazebo/build \
    GZ_SIM_RESOURCE_PATH=/opt/ardupilot_gazebo/models:/opt/ardupilot_gazebo/worlds

# SITL parameter overlay — FCU data-stream rates (see the file's header).
COPY docker/sitl-params.parm /opt/orynth/sitl-params.parm
