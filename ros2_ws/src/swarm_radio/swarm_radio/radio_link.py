"""Radio link transport for the Orynth swarm dialect (ADR 0009).

This module owns the wire format and serial I/O for inter-drone MAVLink-radio
communication. It is deliberately self-contained: no pymavlink dependency, no
generated dialect module — just a manual MAVLink2-shaped framing of the five
ORYNTH_* messages defined in ``external/mavlink_dialects/orynth_swarm.xml``.

Why hand-rolled framing:
  - Only five message types; codegen is overkill.
  - SiK firmware looks for the MAVLink v2 STX (0xFD) to align radio packets;
    using the same magic byte gets us the alignment optimisation for free
    even though we don't fully implement crc_extra signing.
  - Pure-Python, easy to mock for tests via the ``Transport`` abstraction.

Frame layout (mirrors MAVLink2 wire format, no signing):

    byte  0  : 0xFD              STX
    byte  1  : payload length    1B (0..255)
    byte  2  : incompat flags    1B (always 0; signing not used)
    byte  3  : compat flags      1B (always 0)
    byte  4  : sequence          1B (per-sender rolling counter)
    byte  5  : sysid             1B (sender's drone_id)
    byte  6  : compid            1B (always 0)
    bytes 7-9: msgid (24-bit LE) 3B (220..224, upper bytes 0)
    bytes 10-: payload           NB (struct-packed)
    last 2 B : CRC16 X.25        over [len..payload]
"""

from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

STX = 0xFD

MSG_DRONE_STATE = 220
MSG_SETPOINT = 221
MSG_COMMAND = 222
MSG_ACK = 223
MSG_HEARTBEAT = 224
MSG_MOTOR_TEST = 225

# struct formats match field order in orynth_swarm.xml. Little-endian.
_FMT_DRONE_STATE = "<QBffffBBB8s"   # 1+8+4+4+4+4+1+1+1+8 = 36 bytes payload
_FMT_SETPOINT = "<QBffffH"          # 8+1+4+4+4+4+2       = 27 bytes payload
_FMT_COMMAND = "<QBHBf"             # 8+1+2+1+4           = 16 bytes payload
_FMT_ACK = "<QBHB40s"               # 8+1+2+1+40          = 52 bytes payload
_FMT_HEARTBEAT = "<QBBI"            # 8+1+1+4             = 14 bytes payload
_FMT_MOTOR_TEST = "<QBHBBB"         # 8+1+2+1+1+1         = 14 bytes payload

BROADCAST_DRONE_ID = 255


@dataclass(frozen=True)
class DroneState:
    time_boot_ms: int
    drone_id: int
    x: float
    y: float
    z: float
    yaw_rad: float
    armed: bool
    ekf_ok: bool
    battery_pct: int
    mode: str


@dataclass(frozen=True)
class Setpoint:
    time_boot_ms: int
    drone_id: int
    x: float
    y: float
    z: float
    yaw_rad: float
    reference_age_ms: int


@dataclass(frozen=True)
class Command:
    time_boot_ms: int
    drone_id: int
    seq: int
    cmd: int
    param_f: float


@dataclass(frozen=True)
class Ack:
    time_boot_ms: int
    drone_id: int
    seq: int
    success: bool
    message: str


@dataclass(frozen=True)
class Heartbeat:
    time_boot_ms: int
    drone_id: int
    role: int
    uptime_s: int


@dataclass(frozen=True)
class MotorTest:
    time_boot_ms: int
    drone_id: int
    seq: int
    motor_index: int
    throttle_pct: int
    duration_s: int


def _crc16_x25(data: bytes) -> int:
    """X.25 CRC (poly 0x1021, init 0xFFFF, reflected). MAVLink-compatible."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc & 0xFFFF


def _truncate_str(s: str, n: int) -> bytes:
    encoded = s.encode("utf-8", errors="ignore")[:n]
    return encoded.ljust(n, b"\x00")


def _decode_str(raw: bytes) -> str:
    return raw.rstrip(b"\x00").decode("utf-8", errors="ignore")


class Transport(Protocol):
    """Minimal transport interface — anything with read/write/close."""

    def read(self, n: int) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def close(self) -> None: ...


class SerialTransport:
    """Real serial-port transport. Imported lazily so tests don't need pyserial."""

    def __init__(self, device: str, baud: int = 57600, read_timeout_s: float = 0.05):
        import serial  # local import: only required for real hardware

        self._ser = serial.Serial(device, baudrate=baud, timeout=read_timeout_s)

    def read(self, n: int) -> bytes:
        return self._ser.read(n)

    def write(self, data: bytes) -> int:
        return self._ser.write(data)

    def close(self) -> None:
        self._ser.close()


class LoopbackTransport:
    """In-memory transport for tests: bytes written to A are readable from B."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._lock = threading.Lock()
        self.peer: "LoopbackTransport | None" = None

    @classmethod
    def pair(cls) -> "tuple[LoopbackTransport, LoopbackTransport]":
        a, b = cls(), cls()
        a.peer, b.peer = b, a
        return a, b

    def read(self, n: int) -> bytes:
        with self._lock:
            out = bytes(self._buf[:n])
            del self._buf[:n]
            return out

    def write(self, data: bytes) -> int:
        if self.peer is None:
            return 0
        with self.peer._lock:
            self.peer._buf.extend(data)
        return len(data)

    def close(self) -> None:
        self.peer = None


class RadioLink:
    """MAVLink-shaped framing over a Transport, with per-peer rx tracking.

    The link is single-threaded by default: call ``poll()`` from a ROS 2 timer
    to drain incoming frames. ``send_*`` methods are safe to call from any
    thread (they hold an internal lock around the write).
    """

    MAX_FRAME = 280  # 12 header/CRC + 255 payload, plenty of slack

    def __init__(self, transport: Transport, *, local_drone_id: int):
        self._tx = transport
        self._local_id = int(local_drone_id) & 0xFF
        self._tx_seq = 0
        self._tx_lock = threading.Lock()
        self._rx_buf = bytearray()
        self._peer_rx_mono: dict[int, float] = {}
        self._t0 = time.monotonic()

    # ── lifecycle ──────────────────────────────────────────────────────────
    def close(self) -> None:
        try:
            self._tx.close()
        except Exception:
            pass

    # ── time helpers ───────────────────────────────────────────────────────
    def boot_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000) & 0xFFFFFFFFFFFFFFFF

    def peer_age_s(self, drone_id: int) -> float:
        """Seconds since last frame seen from ``drone_id``. ``inf`` if never."""
        last = self._peer_rx_mono.get(int(drone_id) & 0xFF)
        if last is None:
            return float("inf")
        return time.monotonic() - last

    # ── encoders ───────────────────────────────────────────────────────────
    def send_drone_state(self, state: DroneState) -> None:
        payload = struct.pack(
            _FMT_DRONE_STATE,
            state.time_boot_ms & 0xFFFFFFFFFFFFFFFF,
            state.drone_id & 0xFF,
            float(state.x),
            float(state.y),
            float(state.z),
            float(state.yaw_rad),
            1 if state.armed else 0,
            1 if state.ekf_ok else 0,
            max(0, min(100, int(state.battery_pct))),
            _truncate_str(state.mode, 8),
        )
        self._send_frame(MSG_DRONE_STATE, payload)

    def send_setpoint(self, sp: Setpoint) -> None:
        payload = struct.pack(
            _FMT_SETPOINT,
            sp.time_boot_ms & 0xFFFFFFFFFFFFFFFF,
            sp.drone_id & 0xFF,
            float(sp.x),
            float(sp.y),
            float(sp.z),
            float(sp.yaw_rad),
            int(sp.reference_age_ms) & 0xFFFF,
        )
        self._send_frame(MSG_SETPOINT, payload)

    def send_command(self, cmd: Command) -> None:
        payload = struct.pack(
            _FMT_COMMAND,
            cmd.time_boot_ms & 0xFFFFFFFFFFFFFFFF,
            cmd.drone_id & 0xFF,
            int(cmd.seq) & 0xFFFF,
            int(cmd.cmd) & 0xFF,
            float(cmd.param_f),
        )
        self._send_frame(MSG_COMMAND, payload)

    def send_ack(self, ack: Ack) -> None:
        payload = struct.pack(
            _FMT_ACK,
            ack.time_boot_ms & 0xFFFFFFFFFFFFFFFF,
            ack.drone_id & 0xFF,
            int(ack.seq) & 0xFFFF,
            1 if ack.success else 0,
            _truncate_str(ack.message, 40),
        )
        self._send_frame(MSG_ACK, payload)

    def send_heartbeat(self, hb: Heartbeat) -> None:
        payload = struct.pack(
            _FMT_HEARTBEAT,
            hb.time_boot_ms & 0xFFFFFFFFFFFFFFFF,
            hb.drone_id & 0xFF,
            int(hb.role) & 0xFF,
            int(hb.uptime_s) & 0xFFFFFFFF,
        )
        self._send_frame(MSG_HEARTBEAT, payload)

    def send_motor_test(self, mt: MotorTest) -> None:
        payload = struct.pack(
            _FMT_MOTOR_TEST,
            mt.time_boot_ms & 0xFFFFFFFFFFFFFFFF,
            mt.drone_id & 0xFF,
            int(mt.seq) & 0xFFFF,
            int(mt.motor_index) & 0xFF,
            int(mt.throttle_pct) & 0xFF,
            int(mt.duration_s) & 0xFF,
        )
        self._send_frame(MSG_MOTOR_TEST, payload)

    # ── poll ───────────────────────────────────────────────────────────────
    def poll(self, max_bytes: int = 1024) -> Iterable[object]:
        """Drain available bytes and yield decoded messages.

        Yields any subset of DroneState / Setpoint / Command / Ack / Heartbeat.
        Malformed or unknown frames are dropped silently — the rx loop is
        responsible for resyncing on the next STX byte.
        """
        chunk = self._tx.read(max_bytes)
        if chunk:
            self._rx_buf.extend(chunk)
        yield from self._drain()

    # ── internals ──────────────────────────────────────────────────────────
    def _send_frame(self, msg_id: int, payload: bytes) -> None:
        if len(payload) > 255:
            raise ValueError(f"payload too large: {len(payload)} bytes")
        with self._tx_lock:
            seq = self._tx_seq & 0xFF
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            header = struct.pack(
                "<BBBBBBBBB",
                len(payload),
                0,          # incompat flags
                0,          # compat flags
                seq,
                self._local_id,
                0,          # compid
                msg_id & 0xFF,
                (msg_id >> 8) & 0xFF,
                (msg_id >> 16) & 0xFF,
            )
            crc = _crc16_x25(header + payload)
            frame = bytes([STX]) + header + payload + struct.pack("<H", crc)
            self._tx.write(frame)

    def _drain(self):
        buf = self._rx_buf
        while True:
            stx_idx = buf.find(STX)
            if stx_idx < 0:
                buf.clear()
                return
            if stx_idx > 0:
                del buf[:stx_idx]
            # Need at least STX + 9 header + 2 CRC = 12 bytes to read length.
            if len(buf) < 12:
                return
            payload_len = buf[1]
            frame_len = 1 + 9 + payload_len + 2
            if len(buf) < frame_len:
                return
            header = bytes(buf[1:10])
            payload = bytes(buf[10:10 + payload_len])
            crc_bytes = bytes(buf[10 + payload_len:12 + payload_len])
            (rx_crc,) = struct.unpack("<H", crc_bytes)
            if _crc16_x25(header + payload) != rx_crc:
                # Drop the STX byte and resync on next candidate.
                del buf[:1]
                continue
            sysid = header[4]
            msg_id = header[6] | (header[7] << 8) | (header[8] << 16)
            del buf[:frame_len]
            self._peer_rx_mono[sysid] = time.monotonic()
            decoded = self._decode(msg_id, payload)
            if decoded is not None:
                yield decoded

    def _decode(self, msg_id: int, payload: bytes):
        try:
            if msg_id == MSG_DRONE_STATE:
                (
                    t_ms, drone_id, x, y, z, yaw, armed, ekf_ok, batt, mode_b,
                ) = struct.unpack(_FMT_DRONE_STATE, payload)
                return DroneState(
                    time_boot_ms=t_ms, drone_id=drone_id, x=x, y=y, z=z,
                    yaw_rad=yaw, armed=bool(armed), ekf_ok=bool(ekf_ok),
                    battery_pct=batt, mode=_decode_str(mode_b),
                )
            if msg_id == MSG_SETPOINT:
                t_ms, drone_id, x, y, z, yaw, ref_age = struct.unpack(
                    _FMT_SETPOINT, payload,
                )
                return Setpoint(
                    time_boot_ms=t_ms, drone_id=drone_id, x=x, y=y, z=z,
                    yaw_rad=yaw, reference_age_ms=ref_age,
                )
            if msg_id == MSG_COMMAND:
                t_ms, drone_id, seq, cmd, param_f = struct.unpack(
                    _FMT_COMMAND, payload,
                )
                return Command(
                    time_boot_ms=t_ms, drone_id=drone_id, seq=seq,
                    cmd=cmd, param_f=param_f,
                )
            if msg_id == MSG_ACK:
                t_ms, drone_id, seq, success, msg_b = struct.unpack(
                    _FMT_ACK, payload,
                )
                return Ack(
                    time_boot_ms=t_ms, drone_id=drone_id, seq=seq,
                    success=bool(success), message=_decode_str(msg_b),
                )
            if msg_id == MSG_HEARTBEAT:
                t_ms, drone_id, role, uptime = struct.unpack(
                    _FMT_HEARTBEAT, payload,
                )
                return Heartbeat(
                    time_boot_ms=t_ms, drone_id=drone_id, role=role,
                    uptime_s=uptime,
                )
            if msg_id == MSG_MOTOR_TEST:
                t_ms, drone_id, seq, motor, throttle, duration = struct.unpack(
                    _FMT_MOTOR_TEST, payload,
                )
                return MotorTest(
                    time_boot_ms=t_ms, drone_id=drone_id, seq=seq,
                    motor_index=motor, throttle_pct=throttle,
                    duration_s=duration,
                )
        except struct.error:
            return None
        return None


def open_serial_link(
    device: str,
    *,
    local_drone_id: int,
    baud: int = 57600,
    factory: Callable[[str, int], Transport] | None = None,
) -> RadioLink:
    """Convenience constructor for hardware: opens a serial port and wraps it."""
    if factory is None:
        transport: Transport = SerialTransport(device, baud=baud)
    else:
        transport = factory(device, baud)
    return RadioLink(transport, local_drone_id=local_drone_id)
