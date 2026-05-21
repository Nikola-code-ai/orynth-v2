# syntax=docker/dockerfile:1.7
# Developer image — base + interactive tooling.
ARG BASE_TAG=orynth-base:latest
FROM ${BASE_TAG}

RUN apt-get update && apt-get install -y --no-install-recommends \
      vim less curl iputils-ping iproute2 net-tools \
      gdb clang-format clang-tidy \
      tmux ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
      pre-commit==3.7.1 \
      black==24.4.2 \
      ruff==0.4.4

CMD ["bash"]
