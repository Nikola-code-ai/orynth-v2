"""Generate a Gazebo Harmonic world holding N ArduPilot SITL drones.

Phase 2 (ADR 0003). The stock ``ardupilot_gazebo`` ships a single-vehicle
``iris_runway`` world; a swarm needs N vehicles, each with a *distinct*
``ArduPilotPlugin`` FDM port so SITL instance ``i`` talks to model ``drone_i``.

This module stamps the world out programmatically: it keeps the
``iris_runway`` skeleton (physics, sensor/IMU/NavSat systems, lighting,
spherical coordinates) and replaces its lone vehicle with ``drone_0``..
``drone_<N-1>`` — each a copy of ``iris_with_ardupilot`` at an offset spawn
with FDM port ``9002 + 10*i`` (the per-instance offset SITL's ``--instance``
applies).

Pure Python / standard library only — no ROS, no Gazebo import — so it stays
unit-testable and runs as part of the sim-container entrypoint.
"""

from __future__ import annotations

import argparse
import re
import sys

#: In-image paths provided by docker/sitl.Dockerfile (ardupilot_gazebo).
DEFAULT_MODEL_SDF = "/opt/ardupilot_gazebo/models/iris_with_ardupilot/model.sdf"
DEFAULT_WORLD_TEMPLATE = "/opt/ardupilot_gazebo/worlds/iris_runway.sdf"

#: ArduPilotPlugin FDM base port; SITL instance i uses base + 10*i.
FDM_BASE_PORT = 9002
#: Iris sits slightly above ground so the legs do not clip the plane.
SPAWN_Z_M = 0.195
#: Model yaw — matches the stock iris_runway spawn.
SPAWN_YAW_DEG = 90.0


def _model_inner(model_sdf_text: str) -> str:
    """Return the body of the ``iris_with_ardupilot`` ``<model>`` element.

    Everything between the opening ``<model ...>`` tag and the final
    ``</model>`` — i.e. the included airframe plus the ArduPilotPlugin.
    """
    open_match = re.search(r"<model\b[^>]*>", model_sdf_text)
    if open_match is None:
        raise ValueError("base model SDF has no <model> element")
    close_idx = model_sdf_text.rindex("</model>")
    return model_sdf_text[open_match.end() : close_idx]


def drone_model_block(
    index: int,
    east_m: float,
    north_m: float,
    inner: str,
    *,
    spawn_z_m: float = SPAWN_Z_M,
    yaw_deg: float = SPAWN_YAW_DEG,
) -> str:
    """Build the ``<model name="drone_i">`` block for one swarm vehicle."""
    fdm_port = FDM_BASE_PORT + 10 * index
    # Give this copy its own FDM port so SITL instance i reaches drone_i.
    ported = re.sub(
        r"<fdm_port_in>\s*\d+\s*</fdm_port_in>",
        f"<fdm_port_in>{fdm_port}</fdm_port_in>",
        inner,
        count=1,
    )
    return (
        f'    <model name="drone_{index}">\n'
        f'      <pose degrees="true">'
        f"{east_m:.3f} {north_m:.3f} {spawn_z_m:.3f} 0 0 {yaw_deg:.1f}</pose>"
        f"{ported}"
        f"    </model>\n"
    )


def build_world(
    drone_count: int,
    spacing_m: float = 5.0,
    *,
    model_sdf_path: str = DEFAULT_MODEL_SDF,
    world_template_path: str = DEFAULT_WORLD_TEMPLATE,
) -> str:
    """Return the SDF text for an N-drone Orynth swarm world.

    Drones spawn in a row centred on the world origin, ``spacing_m`` apart
    along East, so they are visually separated and never spawn intersecting.
    """
    if drone_count < 1:
        raise ValueError(f"drone_count must be >= 1, got {drone_count}")
    if spacing_m <= 0.0:
        raise ValueError(f"spacing_m must be > 0, got {spacing_m}")

    with open(world_template_path, encoding="utf-8") as fh:
        world = fh.read()
    with open(model_sdf_path, encoding="utf-8") as fh:
        inner = _model_inner(fh.read())

    # Drop the template's single demo vehicle — the swarm replaces it.
    world = re.sub(
        r"[ \t]*<include>\s*<uri>model://iris_with_gimbal</uri>.*?</include>\n?",
        "",
        world,
        flags=re.DOTALL,
    )
    world = world.replace('<world name="iris_runway">', '<world name="orynth_swarm">')

    half = (drone_count - 1) / 2.0
    blocks = "".join(
        drone_model_block(i, (i - half) * spacing_m, 0.0, inner)
        for i in range(drone_count)
    )
    return world.replace("  </world>", f"{blocks}  </world>")


def main(argv: list[str] | None = None) -> int:
    """Write a swarm world to disk — ``python -m swarm_sim.world_builder``."""
    parser = argparse.ArgumentParser(description="Generate an Orynth swarm world.")
    parser.add_argument("--drones", type=int, default=5)
    parser.add_argument("--spacing", type=float, default=5.0)
    parser.add_argument("--out", default="/tmp/orynth_swarm.sdf")
    parser.add_argument("--model-sdf", default=DEFAULT_MODEL_SDF)
    parser.add_argument("--world-template", default=DEFAULT_WORLD_TEMPLATE)
    args = parser.parse_args(argv)

    world = build_world(
        args.drones,
        args.spacing,
        model_sdf_path=args.model_sdf,
        world_template_path=args.world_template,
    )
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(world)
    print(f"wrote {args.drones}-drone world -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
