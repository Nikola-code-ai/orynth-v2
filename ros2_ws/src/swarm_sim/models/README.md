# swarm_sim — custom airframe meshes

Visual geometry for the Gazebo swarm world. The SITL flight model is
unchanged: `world_builder.py` keeps the stock `iris_with_ardupilot` links,
collisions, inertias, rotors and `ArduPilotPlugin` intact, and only swaps the
**visual** mesh of the airframe body. The drones *look* like the Orynth
airframe; they still *fly* as the tuned iris model.

## Expected asset

| Property      | Required value                                          |
|---------------|---------------------------------------------------------|
| File          | `orynth_drone.glb`                                      |
| Format        | glTF 2.0 binary (`.glb`), self-contained (textures embedded) |
| Units         | metres — drone ~0.3–0.6 m across, **not** ~300–600      |
| Up axis       | glTF Y-up convention (SolidWorks writes the root transform); the SDF visual `<pose>` applies the Y-up → Z-up fix |
| Forward axis  | airframe nose along model +X after the Z-up fix         |
| Origin        | mesh centred on the body centre of mass                 |
| Triangles     | keep moderate (≲150k) — the world spawns 5 copies       |

## How it is exported (SolidWorks)

`File ▸ Save As ▸ glTF Binary (*.glb)` — embed textures, medium tessellation
quality. The `.SLDASM` assembly is flattened into one self-contained `.glb`;
no separate `.SLDPRT` part files are needed.

## How it is consumed

Drop `orynth_drone.glb` in this directory. `world_builder.py` references it as
the base-link visual mesh; the SITL container exposes this path on
`GZ_SIM_RESOURCE_PATH` so Gazebo's resource finder can resolve it. With no
`.glb` present, the world falls back to the stock iris visual.
