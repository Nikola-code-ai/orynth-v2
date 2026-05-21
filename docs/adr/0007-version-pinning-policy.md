# ADR 0007: Version-pinning policy

**Status**: accepted · **Date**: 2026-05-21

## Context

v1 used floating apt versions, a `latest`-tagged Docker base image (`aerostack2/nightly-humble:latest`), and unpinned pip installs. A rebuild three months from a working state is a coin-flip — and a coin-flip on flight-critical software is unacceptable.

## Decision

Every external dependency is pinned. No exceptions.

| Layer | Mechanism | Example |
|---|---|---|
| Docker base images | SHA256 digest (not tag) | `FROM ros:humble-ros-base-jammy@sha256:abc123...` |
| apt packages | `pkg=version` per line | `RUN apt-get install -y ros-humble-mavros=2.5.0-1jammy.20240310...` |
| Python | `requirements.txt` + `pip install --require-hashes` | `ultralytics==8.2.0 --hash=sha256:...` |
| ROS packages from source | `vcstool` + git SHA in `.repos` | `version: 1a2b3c4d...` |
| ML model weights | Git LFS + SHA256 in `config/models/manifest.yaml` | `yolov8n.pt: sha256:def456...` |

## Operational rules

- `digests.lock` enumerates every Docker digest. CI verifies that no Dockerfile uses an unpinned `FROM`.
- Quarterly: maintainer runs `scripts/build/refresh_pins.sh`, which produces a PR updating digests + SHAs. PR must include test results.
- Emergency security patches bypass quarterly cadence but still produce a digest update PR.
- `scripts/build/build_workspace.sh` fails loudly if it detects any unpinned dependency (grep for `:latest`, `~=`, `^=`, or empty SHA fields).

## Consequences

- Build is bit-reproducible (within the limits of CUDA driver matching on Jetson).
- Updates are deliberate, batched, tested.
- "It worked yesterday, broken today" cannot be caused by silent upstream changes.
- One drawback: contributors must run `refresh_pins.sh` to add a new dep. Documented in `docs/runbooks/sitl_swarm_dev.md`.
