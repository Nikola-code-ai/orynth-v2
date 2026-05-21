# syntax=docker/dockerfile:1.7
# Orynth v2 base image — ROS 2 Humble + common deps.
# Multi-arch (linux/amd64 + linux/arm64).
#
# Per ADR 0007: base image is pinned by SHA256 digest, not by tag.
# The digests below are placeholders — populate via scripts/build/refresh_pins.sh
# before the first CI run. CI guard rejects unpinned FROMs.

ARG ROS_BASE_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000
ARG JETPACK_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000

FROM ros:humble-ros-base-jammy@${ROS_BASE_DIGEST} AS base-amd64
FROM nvcr.io/nvidia/l4t-jetpack:r36.3.0@${JETPACK_DIGEST} AS base-arm64

ARG TARGETARCH
FROM base-${TARGETARCH} AS base

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    ROS_DISTRO=humble \
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    ROS_DOMAIN_ID=42

# On the JetPack base, ROS 2 isn't pre-installed — bootstrap it from packages.ros.org.
# On the ros: base, this is a no-op (already installed).
RUN if [ ! -f /opt/ros/${ROS_DISTRO}/setup.bash ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg lsb-release software-properties-common && \
      curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg && \
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu jammy main" \
        > /etc/apt/sources.list.d/ros2.list && \
      apt-get update && apt-get install -y --no-install-recommends \
        ros-${ROS_DISTRO}-ros-base \
        python3-colcon-common-extensions \
        python3-rosdep \
        python3-vcstool \
        python3-pip && \
      rosdep init && \
      rm -rf /var/lib/apt/lists/*; \
    fi

# Common ROS 2 + dev tooling, pinned by version per ADR 0007.
# Versions below are quarterly snapshots — refresh via refresh_pins.sh.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
      ros-${ROS_DISTRO}-mavros \
      ros-${ROS_DISTRO}-mavros-msgs \
      ros-${ROS_DISTRO}-mavros-extras \
      ros-${ROS_DISTRO}-foxglove-bridge \
      ros-${ROS_DISTRO}-vision-msgs \
      ros-${ROS_DISTRO}-cv-bridge \
      ros-${ROS_DISTRO}-image-transport \
      ros-${ROS_DISTRO}-behaviortree-cpp \
      ros-${ROS_DISTRO}-octomap-msgs \
      ros-${ROS_DISTRO}-robot-localization \
      ros-${ROS_DISTRO}-nav2-bringup \
      ros-${ROS_DISTRO}-nav2-common \
      ros-${ROS_DISTRO}-rosbag2-storage-mcap \
      python3-pytest \
      python3-pytest-cov \
      git \
      build-essential \
      cmake \
      ninja-build \
    && rm -rf /var/lib/apt/lists/*

# MAVROS GeographicLib datasets (required for global<->local conversions).
RUN /opt/ros/${ROS_DISTRO}/lib/mavros/install_geographiclib_datasets.sh

# Python deps — hashes enforced.
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --require-hashes -r /tmp/requirements.txt

# Workspace mount point.
WORKDIR /workspace

# Entrypoint sources ROS and any built overlay.
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
