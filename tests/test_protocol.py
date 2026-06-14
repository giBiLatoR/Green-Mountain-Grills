"""Tests for the GMG wire protocol parser and command builders.

These tests run against the public surface of the protocol module
(:mod:`custom_components.gmg.api.protocol`). Field offsets mirror the live
36-byte status frame produced by the controller and documented in
``docs/PROTOCOL.md``.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from custom_components.gmg.api.protocol import (
    GMGInvalidValueError,
    GMGProtocolError,
    encode_set_grill_temp,
    encode_set_probe_target,
    parse_status_frame,
)

if TYPE_CHECKING:
    from custom_components.gmg.api import GMGSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _u16(value: int) -> bytes:
    return struct.pack("<H", value)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _make_frame(
    *,
    header: bytes = b"\x55\x52",
    grill_temp: int = 225,
    probe_1: int = 140,
    grill_set: int = 225,
    probe_2: int = 89,
    probe_2_set: int = 145,
    profile_remaining: int = 0,
    warn_code: int = 0,
    probe_1_set: int = 165,
    power_state: int = 1,
    fire_state: int = 3,
    hopper_pct: int = 80,
    grill_type: int = 3,
) -> bytes:
    """Construct a 36-byte status frame with fields at the live LE offsets.

    Live layout (little-endian):
        header@0 ("UR"), grill@2 (u16), probe1@4 (u16), grill_set@6 (u16),
        probe2@16 (u16), probe2_set@18 (u16), profile_remaining@20 (u32),
        warn@24 (u32), probe1_set@28 (u16), power@30 (u8), fire@32 (u8),
        hopper@33 (u8), grill_type@35 (u8). Total length 36.
    """
    frame = bytearray(36)
    frame[0:2] = header
    frame[2:4] = _u16(grill_temp)
    frame[4:6] = _u16(probe_1)
    frame[6:8] = _u16(grill_set)
    frame[16:18] = _u16(probe_2)
    frame[18:20] = _u16(probe_2_set)
    frame[20:24] = _u32(profile_remaining)
    frame[24:28] = _u32(warn_code)
    frame[28:30] = _u16(probe_1_set)
    frame[30] = power_state
    frame[32] = fire_state
    frame[33] = hopper_pct
    frame[35] = grill_type
    assert len(frame) == 36
    return bytes(frame)


# ---------------------------------------------------------------------------
# Golden frame — real captured datagram
# ---------------------------------------------------------------------------

# Real capture from an idle/off grill. 55 bytes on the wire; the parser slices
# the leading 36 bytes. Mirrors the Android ProtocolTest.parsesRealCapturedFrame.
_GOLDEN_FRAME_HEX = (
    "55 52 48 00 4a 00 96 00 06 03 14 32 19 19 00 00 "
    "00 00 00 00 ff ff ff ff 00 00 00 00 00 00 00 00 "
    "01 00 00 01 00 00 f7 00 fd 44 43 30 31 53 55 46 "
    "30 37 2e 31 00 1c fe"
)
_GOLDEN_FRAME = bytes.fromhex(_GOLDEN_FRAME_HEX.replace(" ", ""))


def test_parse_real_captured_frame() -> None:
    """Golden-frame parity test against a real on-the-wire capture."""
    assert len(_GOLDEN_FRAME) == 55  # full datagram; parser slices [:36]

    snap: GMGSnapshot = parse_status_frame(_GOLDEN_FRAME)

    assert snap.grill_temp == 72
    assert snap.probe_1_temp == 74
    assert snap.grill_set_temp == 150
    assert int(snap.power_state) == 0  # PowerState.OFF
    assert int(snap.fire_state) == 1  # FireState.OFF (idle)
    assert snap.hopper_pct == 0
    assert snap.grill_type == 1
    assert int(snap.warn_code) == 0  # WarnCode.NONE
    assert snap.low_pellet is False
    assert snap.flame_on is False
    assert snap.cold_smoke is False


# ---------------------------------------------------------------------------
# Parse tests
# ---------------------------------------------------------------------------


def test_parse_baseline_frame() -> None:
    frame = _make_frame(
        grill_temp=225,
        probe_1=140,
        grill_set=225,
        power_state=1,
        fire_state=3,
        warn_code=0,
    )
    snap: GMGSnapshot = parse_status_frame(frame)

    assert snap.grill_temp == 225
    assert snap.grill_set_temp == 225
    assert snap.probe_1_temp == 140
    assert snap.probe_1_target == 165
    assert int(snap.power_state) == 1
    assert int(snap.fire_state) == 3
    assert snap.flame_on is True
    assert snap.low_pellet is False
    assert snap.cold_smoke is False


def test_parse_probe_sentinel_means_unplugged() -> None:
    frame = _make_frame(probe_1=89)
    snap = parse_status_frame(frame)
    assert snap.probe_1_temp is None


def test_parse_low_pellet_code_8() -> None:
    frame = _make_frame(warn_code=8)
    snap = parse_status_frame(frame)
    assert snap.low_pellet is True


def test_parse_low_pellet_code_128_alias() -> None:
    frame = _make_frame(warn_code=128)
    snap = parse_status_frame(frame)
    assert snap.low_pellet is True


def test_parse_cold_smoke_power_state() -> None:
    frame = _make_frame(power_state=3)
    snap = parse_status_frame(frame)
    assert snap.cold_smoke is True


def test_parse_short_frame_raises() -> None:
    with pytest.raises(GMGProtocolError):
        parse_status_frame(b"\x55\x52\x00\x00")


def test_parse_wrong_header_raises() -> None:
    frame = _make_frame(header=b"\x00\x00")
    with pytest.raises(GMGProtocolError):
        parse_status_frame(frame)


# ---------------------------------------------------------------------------
# Command builder tests
# ---------------------------------------------------------------------------


def test_encode_set_grill_temp_basic() -> None:
    assert encode_set_grill_temp(225) == b"UT225!"


def test_encode_set_probe_target_probe_1_uppercase() -> None:
    assert encode_set_probe_target(1, 165) == b"UF165!"


def test_encode_set_probe_target_probe_2_lowercase() -> None:
    assert encode_set_probe_target(2, 145) == b"Uf145!"


@pytest.mark.parametrize("bad_temp", [-1, 0, 149, 551, 1000])
def test_encode_set_grill_temp_out_of_range_raises(bad_temp: int) -> None:
    with pytest.raises(GMGInvalidValueError):
        encode_set_grill_temp(bad_temp)


@pytest.mark.parametrize("bad_temp", [-1, 0, 31, 258, 999])
def test_encode_set_probe_target_out_of_range_raises(bad_temp: int) -> None:
    with pytest.raises(GMGInvalidValueError):
        encode_set_probe_target(1, bad_temp)
