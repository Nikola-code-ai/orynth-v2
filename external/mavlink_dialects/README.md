# Orynth MAVLink dialects

This directory holds custom MAVLink XML dialects used by Orynth v2.

## `orynth_swarm.xml`

Inter-drone swarm coordination over SiK/RFD900 radio links. Defines five
messages (220–224) consumed by the `swarm_radio` package. See
`docs/adr/0009-mavlink-radio-supersedes-dds-intra-swarm.md`.

## Loading at runtime

`swarm_radio` does not generate Python bindings at build time. Instead,
`swarm_radio/dialect.py` loads `orynth_swarm.xml` directly via
`pymavlink.mavutil.mavlink_connection` with the XML path provided through the
`MAVLINK20=1` + `MAVLINK_DIALECT=orynth_swarm` env vars **or** via a
`MAVLink_orynth` class produced by `mavgen` at install time (see below).
Runtime loading keeps `colcon build` reproducible without invoking codegen.

## Optional: ahead-of-time codegen

If you prefer a generated module instead of runtime loading:

```bash
python3 -m pymavlink.tools.mavgen \
  --lang=Python \
  --wire-protocol=2.0 \
  --output=external/mavlink_dialects/generated/orynth_swarm \
  external/mavlink_dialects/orynth_swarm.xml
```

The generated module is consumed by `swarm_radio.dialect` if present; otherwise
the runtime loader is used.

## Adding a new message

1. Pick an unused id in `[225, 229]` (still inside the user-reserved range).
2. Add the `<message>` block under `orynth_swarm.xml`.
3. Update both `radio_bridge_node.py` (ROS side) and any consumer.
4. Bump `<version>` in the XML and tag the change in the relevant ADR.
