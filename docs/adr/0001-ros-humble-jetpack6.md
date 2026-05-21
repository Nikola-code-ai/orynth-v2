# ADR 0001: ROS 2 Humble on JetPack 6

**Status**: accepted · **Date**: 2026-05-21

## Context

Companion compute on each drone is a Jetson Orin Nano. The most recent JetPack at project start is 6.x, which ships Ubuntu 22.04 (Jammy). ROS 2 has two LTS choices viable for this hardware: Humble (Ubuntu 22.04, Tier-1 binaries) and Jazzy (Ubuntu 24.04, no JetPack support yet).

## Decision

Use **ROS 2 Humble Hawksbill** across the entire stack — dev workstation, SITL, GCS, and Jetson runtime.

## Consequences

- LTS support through May 2027 — covers expected v2.0.0 → v2.1 lifecycle.
- Every external dep (MAVROS, ardupilot_gz, Nav2, RTAB-Map, FAST-LIO2, Isaac ROS) has tested Humble builds.
- Locked out of Jazzy-only features until a future JetPack 7 with Ubuntu 24.04 arrives. Acceptable.
- Workstation devs must use Jammy in containers; native Ubuntu 24.04 dev hosts are fine since we containerize.
