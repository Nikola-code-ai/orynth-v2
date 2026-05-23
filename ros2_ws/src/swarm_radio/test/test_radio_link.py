"""Unit tests for ``swarm_radio.radio_link`` — pure-Python, no ROS required.

Covers:
  - encode/decode round-trip for every ORYNTH_* message type
  - resync after a corrupted byte mid-stream
  - per-peer age tracking via ``peer_age_s``
  - LoopbackTransport behaviour (FIFO, paired)
"""

from __future__ import annotations

import struct
import time

import pytest

from swarm_radio.radio_link import (
    Ack,
    Command,
    DroneState,
    Heartbeat,
    LoopbackTransport,
    MotorTest,
    RadioLink,
    Setpoint,
    STX,
    _crc16_x25,
)


# ── Loopback plumbing ────────────────────────────────────────────────────


def _pair_links(id_a: int = 0, id_b: int = 1) -> tuple[RadioLink, RadioLink]:
    """A pair of RadioLink objects connected via paired LoopbackTransports."""
    tx_a, tx_b = LoopbackTransport.pair()
    return (
        RadioLink(tx_a, local_drone_id=id_a),
        RadioLink(tx_b, local_drone_id=id_b),
    )


def _drain(link: RadioLink) -> list[object]:
    return list(link.poll())


# ── Round-trip tests ─────────────────────────────────────────────────────


def test_drone_state_round_trip():
    sender, receiver = _pair_links()
    sent = DroneState(
        time_boot_ms=12345,
        drone_id=1,
        x=1.0, y=-2.0, z=3.5,
        yaw_rad=0.7853,
        armed=True,
        ekf_ok=True,
        battery_pct=87,
        mode="GUIDED",
    )
    sender.send_drone_state(sent)
    msgs = _drain(receiver)
    assert len(msgs) == 1
    got = msgs[0]
    assert isinstance(got, DroneState)
    assert got.drone_id == 1
    assert got.armed is True
    assert got.ekf_ok is True
    assert got.battery_pct == 87
    assert got.mode == "GUIDED"
    assert got.x == pytest.approx(1.0)
    assert got.y == pytest.approx(-2.0)
    assert got.z == pytest.approx(3.5)
    assert got.yaw_rad == pytest.approx(0.7853, abs=1e-4)


def test_setpoint_round_trip():
    sender, receiver = _pair_links()
    sender.send_setpoint(
        Setpoint(time_boot_ms=99, drone_id=2, x=10.0, y=20.0, z=5.0,
                 yaw_rad=1.57, reference_age_ms=42)
    )
    msgs = _drain(receiver)
    assert len(msgs) == 1
    sp = msgs[0]
    assert isinstance(sp, Setpoint)
    assert sp.drone_id == 2
    assert sp.reference_age_ms == 42
    assert sp.x == pytest.approx(10.0)


def test_command_round_trip():
    sender, receiver = _pair_links()
    sender.send_command(Command(time_boot_ms=1, drone_id=3, seq=7, cmd=3, param_f=2.5))
    msgs = _drain(receiver)
    assert len(msgs) == 1
    cmd = msgs[0]
    assert isinstance(cmd, Command)
    assert (cmd.drone_id, cmd.seq, cmd.cmd) == (3, 7, 3)
    assert cmd.param_f == pytest.approx(2.5)


def test_ack_round_trip():
    sender, receiver = _pair_links()
    sender.send_ack(
        Ack(time_boot_ms=1, drone_id=4, seq=9, success=True, message="ok")
    )
    msgs = _drain(receiver)
    assert len(msgs) == 1
    ack = msgs[0]
    assert isinstance(ack, Ack)
    assert ack.seq == 9
    assert ack.success is True
    assert ack.message == "ok"


def test_motor_test_round_trip():
    sender, receiver = _pair_links()
    sender.send_motor_test(
        MotorTest(time_boot_ms=10, drone_id=1, seq=11,
                  motor_index=3, throttle_pct=12, duration_s=2)
    )
    [mt] = _drain(receiver)
    assert isinstance(mt, MotorTest)
    assert (mt.drone_id, mt.seq, mt.motor_index) == (1, 11, 3)
    assert (mt.throttle_pct, mt.duration_s) == (12, 2)


def test_heartbeat_round_trip():
    sender, receiver = _pair_links()
    sender.send_heartbeat(
        Heartbeat(time_boot_ms=1, drone_id=5, role=1, uptime_s=600)
    )
    msgs = _drain(receiver)
    assert len(msgs) == 1
    hb = msgs[0]
    assert isinstance(hb, Heartbeat)
    assert hb.role == 1
    assert hb.uptime_s == 600


def test_multiple_frames_in_one_poll():
    sender, receiver = _pair_links()
    for i in range(5):
        sender.send_heartbeat(
            Heartbeat(time_boot_ms=i, drone_id=0, role=0, uptime_s=i)
        )
    msgs = _drain(receiver)
    assert len(msgs) == 5
    assert all(isinstance(m, Heartbeat) for m in msgs)
    assert [m.uptime_s for m in msgs] == [0, 1, 2, 3, 4]


# ── Robustness ────────────────────────────────────────────────────────────


def test_long_string_is_truncated():
    sender, receiver = _pair_links()
    long_msg = "x" * 200
    sender.send_ack(Ack(0, 1, 1, True, long_msg))
    [ack] = _drain(receiver)
    assert len(ack.message) == 40
    assert ack.message == "x" * 40


def test_bad_crc_is_dropped_and_link_resyncs():
    sender, receiver = _pair_links()

    # Inject a corrupted STX-prefixed garbage frame, then a valid frame after.
    # The receiver should drop the bad frame and decode the valid one.
    garbage = bytes([STX, 5, 0, 0, 0, 0, 0, 222, 0, 0, 0xAA, 0xAA, 0xAA, 0xAA, 0xAA, 0x00, 0x00])
    receiver._rx_buf.extend(garbage)  # type: ignore[attr-defined]

    sender.send_heartbeat(Heartbeat(0, 1, 0, 1))
    msgs = _drain(receiver)
    assert any(isinstance(m, Heartbeat) for m in msgs)


def test_partial_frame_waits_for_more_bytes():
    sender, receiver = _pair_links()
    sender.send_heartbeat(Heartbeat(0, 1, 0, 1))
    # Pull a partial buffer manually: first half should yield nothing.
    raw = receiver._tx.read(8)  # type: ignore[attr-defined]
    receiver._rx_buf.extend(raw)  # type: ignore[attr-defined]
    assert list(receiver._drain()) == []  # type: ignore[attr-defined]
    # Read the rest.
    rest = receiver._tx.read(1024)  # type: ignore[attr-defined]
    receiver._rx_buf.extend(rest)  # type: ignore[attr-defined]
    msgs = list(receiver._drain())  # type: ignore[attr-defined]
    assert len(msgs) == 1
    assert isinstance(msgs[0], Heartbeat)


# ── Peer age tracking ────────────────────────────────────────────────────


def test_peer_age_inf_before_first_frame():
    _, receiver = _pair_links()
    assert receiver.peer_age_s(0) == float("inf")


def test_peer_age_updates_on_rx():
    sender, receiver = _pair_links(id_a=7, id_b=0)
    sender.send_heartbeat(Heartbeat(0, 7, 0, 1))
    _drain(receiver)
    age = receiver.peer_age_s(7)
    assert 0.0 <= age < 0.2


def test_peer_age_grows():
    sender, receiver = _pair_links(id_a=7, id_b=0)
    sender.send_heartbeat(Heartbeat(0, 7, 0, 1))
    _drain(receiver)
    t1 = receiver.peer_age_s(7)
    time.sleep(0.05)
    t2 = receiver.peer_age_s(7)
    assert t2 > t1


# ── CRC sanity ───────────────────────────────────────────────────────────


def test_crc_zero_bytes_matches_known_value():
    # X.25 CRC of empty input is 0xFFFF.
    assert _crc16_x25(b"") == 0xFFFF


def test_crc_changes_on_payload_flip():
    a = _crc16_x25(b"\x00\x01\x02\x03")
    b = _crc16_x25(b"\x00\x01\x02\x04")
    assert a != b
