<p align="center">
  <img src="docs/assets/banner.png" alt="Orynth — Reaching you when the world cannot." />
</p>

# Orynth v2

5-drone search-and-rescue swarm. ArduPilot flight controllers, Jetson Orin Nano companions, ROS 2 Humble, YOLOv8 human detection, LiDAR mapping on leader, outdoor mission profile.

**Start here**: [`PLAN.md`](PLAN.md) is the canonical implementation plan. Every architectural decision, phase gate, dependency pin, and risk mitigation lives there. [`WORKFLOW.md`](WORKFLOW.md) tracks live status — which phase is in flight, what's done, and any deviations from the plan.

## Status

Phase 0 — scaffold + CI + Docker baseline. See [`WORKFLOW.md`](WORKFLOW.md) for the current checklist and `PLAN.md` § D for the full roadmap.

## Quick links

- Architecture & topic taxonomy: `docs/architecture/`
- Architectural Decision Records: `docs/adr/`
- Bringup, calibration, field deploy runbooks: `docs/runbooks/`
- Hardware BoM & wiring: `docs/hardware/`
- CI pipeline spec: `docs/ci/`

## Hardware

- 5x airframes with ArduPilot Copter 4.5.x flight controllers (Pixhawk-class)
- 5x Jetson Orin Nano companions (JetPack 6 / Ubuntu 22.04)
- 360° LiDAR on leader (`drone_0`) only
- RGB camera on every drone
- Standard ArduPilot sensor suite (IMU, GPS, baro, compass)

## Hard requirements

ROS 2 Humble · Docker · YOLOv8

## v1 → v2

The prior prototype at `../aerolab_ws` was Aerostack2-based; the hardware is ArduPilot. v2 replaces Aerostack2 with MAVROS, adopts Gazebo Harmonic + `ardupilot_gazebo` for sim, ships perception and CI from day one, and pins every dependency by digest. See `PLAN.md` § "v1 Mistakes Being Corrected".
