# Copyright 2026 Google LLC & Contributors
# 帧同步协议/客户端/服务器 pytest 单元测试。
# 运行：python3.11 -m pytest gfootball/frame_sync/protocol_test.py -v

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import socket
import struct
import threading
import time

import pytest

from gfootball.frame_sync.protocol import (
    MessageType,
    SlotInput,
    default_slot_input,
    pack_slot_input,
    unpack_slot_input,
    pack_authoritative_frame,
    unpack_authoritative_frame,
    pack_client_frame_input,
    unpack_client_frame_input,
    pack_session_start,
    unpack_session_start,
    pack_slot_assignment,
    unpack_slot_assignment,
    pack_state_hash,
    unpack_state_hash,
    pack_heartbeat,
    unpack_heartbeat,
    pack_version_negotiate,
    unpack_version_negotiate,
    compute_state_hash,
    SLOT_INPUT_BYTES,
    STATE_HASH_BYTES,
    HEARTBEAT_BYTES,
    SESSION_START_PAYLOAD_BYTES,
    AUTH_FRAME_HEADER_BYTES,
    VERSION_NEGOTIATE_BYTES,
    PROTOCOL_VERSION,
    PROTOCOL_MIN_VERSION,
)
from gfootball.frame_sync.config import (
    FRAME_INPUT_TIMEOUT_MS,
    MAX_PREDICT_AHEAD_FRAMES,
    MAX_FRAMES_WITHOUT_PACKET,
    STATE_HASH_INTERVAL_K,
    HEARTBEAT_INTERVAL_MS,
    HEARTBEAT_MISS_LIMIT,
    RECONNECT_BASE_MS,
    RECONNECT_MAX_MS,
    RECONNECT_MAX_ATTEMPTS,
)


# ===== SlotInput =====

class TestSlotInput:
    def test_default(self):
        s = default_slot_input()
        assert s.dir_x == 0.0
        assert s.dir_y == 0.0
        assert s.buttons == 0

    def test_pack_unpack_roundtrip(self):
        s = SlotInput(1.5, -2.5, 0b10101010)
        buf = pack_slot_input(s)
        s2, offset = unpack_slot_input(buf)
        assert offset == SLOT_INPUT_BYTES
        assert s2.dir_x == 1.5
        assert s2.dir_y == -2.5
        assert s2.buttons == 0b10101010

    def test_binary_size(self):
        assert SLOT_INPUT_BYTES == struct.calcsize('<ffH')

    def test_boundary_values(self):
        for dx, dy, btns in [(0.0, 0.0, 0), (999.9, -999.9, 0xFFFF), (-1.0, 1.0, 1)]:
            s = SlotInput(dx, dy, btns)
            buf = pack_slot_input(s)
            s2, _ = unpack_slot_input(buf)
            assert s2.dir_x == pytest.approx(dx, rel=1e-5)
            assert s2.dir_y == pytest.approx(dy, rel=1e-5)
            assert s2.buttons == btns

    def test_unpack_too_short(self):
        with pytest.raises(ValueError, match='Not enough data'):
            unpack_slot_input(b'\x00\x00')


# ===== MessageType =====

class TestMessageType:
    def test_heartbeat_value(self):
        assert MessageType.Heartbeat == 8

    def test_version_negotiate_value(self):
        assert MessageType.VersionNegotiate == 9

    def test_all_unique(self):
        vals = [
            MessageType.Connect, MessageType.Disconnect, MessageType.FrameInput,
            MessageType.AuthoritativeFrame, MessageType.StateHash,
            MessageType.SessionStart, MessageType.Ready, MessageType.SlotAssignment,
            MessageType.Heartbeat, MessageType.VersionNegotiate,
        ]
        assert len(vals) == len(set(vals))

    def test_all_in_uint8_range(self):
        types = [
            MessageType.Connect, MessageType.Disconnect, MessageType.FrameInput,
            MessageType.AuthoritativeFrame, MessageType.StateHash,
            MessageType.SessionStart, MessageType.Ready, MessageType.SlotAssignment,
            MessageType.Heartbeat, MessageType.VersionNegotiate,
        ]
        for t in types:
            assert 0 <= t <= 255


# ===== AuthoritativeFrame =====

class TestAuthoritativeFrame:
    def test_pack_unpack(self):
        slots = [SlotInput(1.0, -0.5, 0b0011), SlotInput(0.0, 0.0, 0)]
        buf = pack_authoritative_frame(42, slots)
        fid, s = unpack_authoritative_frame(buf)
        assert fid == 42
        assert len(s) == 2
        assert s[0].dir_x == 1.0
        assert s[1].buttons == 0

    def test_empty_slots(self):
        buf = pack_authoritative_frame(0, [])
        fid, s = unpack_authoritative_frame(buf)
        assert fid == 0
        assert s == []

    def test_header_size(self):
        assert AUTH_FRAME_HEADER_BYTES == 1 + 4 + 2  # msg + frame_id + num_slots


# ===== ClientFrameInput =====

class TestClientFrameInput:
    def test_pack_unpack(self):
        entries = [(0, SlotInput(0.5, 0.5, 0b0001)), (2, SlotInput(-1.0, 0.0, 0b1000))]
        buf = pack_client_frame_input(100, entries)
        fid, e = unpack_client_frame_input(buf)
        assert fid == 100
        assert len(e) == 2
        assert e[0] == (0, SlotInput(0.5, 0.5, 0b0001))
        assert e[1] == (2, SlotInput(-1.0, 0.0, 0b1000))

    def test_empty_entries(self):
        buf = pack_client_frame_input(0, [])
        fid, e = unpack_client_frame_input(buf)
        assert fid == 0
        assert e == []

    def test_header_layout(self):
        # 验证 Python 侧 ClientFrameInput 布局
        entries = [(5, SlotInput(1.0, 2.0, 0xFF))]
        buf = pack_client_frame_input(99, entries)
        # msg_type(1) + frame_id(4) + num_slots(2) + slot_index(2) + SlotInput(10) = 19
        assert buf[0] == MessageType.FrameInput
        assert len(buf) == 1 + 4 + 2 + 2 + SLOT_INPUT_BYTES


# ===== SessionStart =====

class TestSessionStart:
    def test_pack_unpack(self):
        buf = pack_session_start(42, 2, 3)
        seed, left, right = unpack_session_start(buf)
        assert seed == 42
        assert left == 2
        assert right == 3

    def test_payload_size(self):
        assert SESSION_START_PAYLOAD_BYTES == 8  # 4 + 2 + 2


# ===== SlotAssignment =====

class TestSlotAssignment:
    def test_pack_unpack(self):
        buf = pack_slot_assignment([0, 5, 10])
        slots = unpack_slot_assignment(buf)
        assert slots == [0, 5, 10]

    def test_single_slot(self):
        buf = pack_slot_assignment([3])
        slots = unpack_slot_assignment(buf)
        assert slots == [3]


# ===== StateHash =====

class TestStateHash:
    def test_pack_unpack(self):
        buf = pack_state_hash(100, 0xDEADBEEFCAFEBABE)
        fid, h = unpack_state_hash(buf)
        assert fid == 100
        assert h == 0xDEADBEEFCAFEBABE

    def test_size(self):
        assert STATE_HASH_BYTES == 1 + 4 + 8  # msg + frame_id + hash64


# ===== Heartbeat =====

class TestHeartbeat:
    def test_pack_unpack(self):
        buf = pack_heartbeat(42, 1234567890)
        fid, ts = unpack_heartbeat(buf)
        assert fid == 42
        assert ts == 1234567890

    def test_size(self):
        assert HEARTBEAT_BYTES == 9  # 1 + 4 + 4

    def test_boundary(self):
        for fid, ts in [(0, 0), (0xFFFFFFFF, 0xFFFFFFFF)]:
            buf = pack_heartbeat(fid, ts)
            f2, t2 = unpack_heartbeat(buf)
            assert f2 == fid
            assert t2 == ts

    def test_rejects_non_heartbeat(self):
        auth = pack_authoritative_frame(1, [default_slot_input()])
        with pytest.raises(ValueError, match='Not Heartbeat'):
            unpack_heartbeat(auth)


# ===== compute_state_hash =====

class TestStateHashCompute:
    def test_consistent(self):
        h1 = compute_state_hash(b'test')
        h2 = compute_state_hash(b'test')
        assert h1 == h2

    def test_different_inputs(self):
        h1 = compute_state_hash(b'abc')
        h2 = compute_state_hash(b'def')
        assert h1 != h2

    def test_64bit_range(self):
        h = compute_state_hash(b'x')
        assert 0 <= h < (1 << 64)


# ===== Config constants =====

class TestVersionNegotiate:
    def test_pack_unpack(self):
        buf = pack_version_negotiate(2, 1)
        ver, min_ver = unpack_version_negotiate(buf)
        assert ver == 2
        assert min_ver == 1

    def test_defaults(self):
        buf = pack_version_negotiate()
        ver, min_ver = unpack_version_negotiate(buf)
        assert ver == PROTOCOL_VERSION
        assert min_ver == PROTOCOL_MIN_VERSION

    def test_size(self):
        assert VERSION_NEGOTIATE_BYTES == 5  # 1 + 2 + 2

    def test_boundary(self):
        buf = pack_version_negotiate(0xFFFF, 0)
        ver, min_ver = unpack_version_negotiate(buf)
        assert ver == 0xFFFF
        assert min_ver == 0

    def test_rejects_non_version(self):
        auth = pack_authoritative_frame(1, [default_slot_input()])
        with pytest.raises(ValueError, match='Not VersionNegotiate'):
            unpack_version_negotiate(auth)


class TestConfig:
    def test_heartbeat(self):
        assert HEARTBEAT_INTERVAL_MS == 1000
        assert HEARTBEAT_MISS_LIMIT == 5

    def test_reconnect(self):
        assert RECONNECT_BASE_MS == 1000
        assert RECONNECT_MAX_MS == 30000
        assert RECONNECT_MAX_ATTEMPTS == 10

    def test_prediction(self):
        assert MAX_PREDICT_AHEAD_FRAMES == 3
        assert MAX_FRAMES_WITHOUT_PACKET == 5

    def test_reconnect_backoff_formula(self):
        base = RECONNECT_BASE_MS
        expected = [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000, 30000, 30000]
        for i, exp in enumerate(expected):
            actual = min(base * (2 ** i), RECONNECT_MAX_MS)
            assert actual == exp, f'attempt {i+1}: {actual} != {exp}'


# ===== Client =====

class TestFrameSyncClient:
    def test_has_reconnect_methods(self):
        from gfootball.frame_sync.client import FrameSyncClient, ReconnectingFrameSyncClient
        assert hasattr(FrameSyncClient, 'reset_for_reconnect')
        assert hasattr(ReconnectingFrameSyncClient, 'tick')
        assert hasattr(ReconnectingFrameSyncClient, 'set_on_reconnect')
        assert hasattr(ReconnectingFrameSyncClient, 'set_on_disconnect')
        assert hasattr(ReconnectingFrameSyncClient, 'set_on_give_up')


# ===== Server =====

class TestFrameSyncServer:
    def test_has_required_methods(self):
        from gfootball.frame_sync.server import FrameSyncServer
        assert hasattr(FrameSyncServer, 'start')
        assert hasattr(FrameSyncServer, 'stop')
        assert hasattr(FrameSyncServer, 'run_one_frame')
        assert hasattr(FrameSyncServer, 'run_loop')


class TestLogicStateHolder:
    def test_write_and_read(self):
        from gfootball.frame_sync.presentation import LogicStateHolder
        holder = LogicStateHolder()
        holder.write('state_1', frame_id=0)
        state, fid, confirmed, ts, waiting = holder.read()
        assert state == 'state_1'
        assert fid == 0
        assert not waiting

    def test_read_interpolated_single_frame(self):
        from gfootball.frame_sync.presentation import LogicStateHolder
        holder = LogicStateHolder()
        holder.write('state_1', frame_id=0)
        state, alpha = holder.read_interpolated()
        assert state == 'state_1'
        assert alpha == 0.0

    def test_read_interpolated_two_frames(self):
        from gfootball.frame_sync.presentation import LogicStateHolder
        holder = LogicStateHolder(buffer_size=4)
        holder.set_logic_fps(10.0)
        holder.write('state_1', frame_id=0)
        time.sleep(0.02)  # 20ms
        holder.write('state_2', frame_id=1)
        state, alpha = holder.read_interpolated()
        assert state == 'state_2'
        assert 0.0 <= alpha <= 1.0

    def test_buffer_depth(self):
        from gfootball.frame_sync.presentation import LogicStateHolder
        holder = LogicStateHolder(buffer_size=3)
        assert holder.buffer_depth == 0
        holder.write('s1', frame_id=0)
        assert holder.buffer_depth == 1
        holder.write('s2', frame_id=1)
        holder.write('s3', frame_id=2)
        assert holder.buffer_depth == 3
        holder.write('s4', frame_id=3)  # 溢出，最旧被丢弃
        assert holder.buffer_depth == 3

    def test_set_logic_fps(self):
        from gfootball.frame_sync.presentation import LogicStateHolder
        holder = LogicStateHolder()
        holder.set_logic_fps(15.0)
        assert holder._logic_fps == 15.0


class TestPresentationLoop:
    def test_has_methods(self):
        from gfootball.frame_sync.presentation import PresentationLoop, LogicStateHolder
        holder = LogicStateHolder()
        # PresentationLoop 需要 display_env mock
        class MockEnv:
            def set_state(self, s): pass
            def render(self): pass
        loop = PresentationLoop(MockEnv(), holder, rate_hz=60)
        assert hasattr(loop, 'run_one_frame')
        assert hasattr(loop, 'run_loop')
        assert hasattr(loop, 'stop')
        assert hasattr(loop, 'get_jitter_stats')
        assert hasattr(loop, 'render_count')

    def test_run_one_frame(self):
        from gfootball.frame_sync.presentation import PresentationLoop, LogicStateHolder
        holder = LogicStateHolder()
        rendered = []
        class MockEnv:
            def set_state(self, s): self._state = s
            def render(self): rendered.append(True)
        loop = PresentationLoop(MockEnv(), holder, rate_hz=60)
        holder.write('test_state', frame_id=0)
        loop.run_one_frame()
        assert len(rendered) == 1
        assert loop.render_count == 1

    def test_jitter_stats_empty(self):
        from gfootball.frame_sync.presentation import PresentationLoop, LogicStateHolder
        loop = PresentationLoop(type('E', (), {'set_state': lambda s: None, 'render': lambda: None})(), LogicStateHolder())
        avg, mx, p95 = loop.get_jitter_stats()
        assert avg == 0.0 and mx == 0.0 and p95 == 0.0
