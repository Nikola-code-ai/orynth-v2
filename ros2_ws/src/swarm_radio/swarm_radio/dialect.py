"""Orynth swarm MAVLink dialect loader.

Resolves the `orynth_swarm.xml` dialect at runtime via pymavlink. We avoid
ahead-of-time codegen at colcon-build time so the package stays buildable
without invoking mavgen. The XML is shipped as a data file inside the source
tree and located by walking up from this module to the repo root.
"""

from __future__ import annotations

import os
from pathlib import Path

# pymavlink reads these env vars at import time. They MUST be set before any
# `pymavlink.dialects` import. We set them here as a side-effect of importing
# this module, then perform the actual import below.
_THIS_DIR = Path(__file__).resolve().parent


def _find_dialect_xml() -> Path:
    """Walk up from this file to find external/mavlink_dialects/orynth_swarm.xml."""
    cur = _THIS_DIR
    for _ in range(8):
        candidate = cur / "external" / "mavlink_dialects" / "orynth_swarm.xml"
        if candidate.is_file():
            return candidate
        cur = cur.parent
    # Fall back to env override if the tree layout differs (e.g. installed share).
    override = os.environ.get("ORYNTH_DIALECT_XML")
    if override and Path(override).is_file():
        return Path(override)
    raise FileNotFoundError(
        "orynth_swarm.xml not found. Set ORYNTH_DIALECT_XML to the dialect path."
    )


DIALECT_XML = _find_dialect_xml()

# Point pymavlink at our XML. MAVLINK20 selects MAVLink2 framing.
os.environ.setdefault("MAVLINK20", "1")
os.environ["MAVLINK_DIALECT"] = str(DIALECT_XML)

# Import after env is set. pymavlink.mavutil supports loading a custom dialect
# XML directly via `mavlink_connection(..., dialect=<path>)`, but the message
# classes also need to be reachable; the cleanest route is mavutil.mavlink.
from pymavlink import mavutil  # noqa: E402

# Cache message class handles for the encoder/decoder. The names match the XML.
MAVLINK_MSG_ID_ORYNTH_DRONE_STATE = 220
MAVLINK_MSG_ID_ORYNTH_SETPOINT = 221
MAVLINK_MSG_ID_ORYNTH_COMMAND = 222
MAVLINK_MSG_ID_ORYNTH_ACK = 223
MAVLINK_MSG_ID_ORYNTH_HEARTBEAT = 224

# Command enum mirror (kept as plain ints so callers don't need the dialect).
CMD_NOOP = 0
CMD_ARM = 1
CMD_DISARM = 2
CMD_TAKEOFF = 3
CMD_LAND = 4
CMD_ABORT = 5
CMD_SET_MODE_GUIDED = 6
CMD_SET_MODE_BRAKE = 7

ROLE_LEADER = 0
ROLE_FOLLOWER = 1

BROADCAST_DRONE_ID = 255


def mav_module():
    """Return the pymavlink mavutil module after dialect env is configured."""
    return mavutil
