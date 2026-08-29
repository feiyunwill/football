# Copyright 2026 Google LLC & Contributors
# UDP-based frame sync client with reliable delivery (matches C++ ReliableUDPChannel).

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import socket
import struct
import threading
import time

from gfootball.frame_sync.protocol import (
    MessageType,
    SlotInput,
    default_slot_input,
    pack_client_frame_input,
    pack_ready,
    pack_version_negotiate,
    compute_state_hash,
    unpack_authoritative_frame,
    unpack_session_start,
    unpack_slot_assignment,
    unpack_state_hash,
    unpack_heartbeat,
    SLOT_INPUT_BYTES,
    STATE_HASH_BYTES,
    HEARTBEAT_BYTES,
    MAX_PREDICT_AHEAD_FRAMES,
    MAX_FRAMES_WITHOUT_PACKET,
)
from gfootball.frame_sync.config import (
    HEARTBEAT_INTERVAL_MS, HEARTBEAT_MISS_LIMIT,
    RECONNECT_BASE_MS, RECONNECT_MAX_MS, RECONNECT_MAX_ATTEMPTS,
)

# Reliable UDP constants (match C++ reliable_udp.hpp)
K_RELIABLE_UDP_DATA = 0x00
K_RELIABLE_UDP_ACK = 0xFF
K_RELIABLE_UDP_HEADER_SIZE = 1 + 4 + 2  # type, seq, len
K_RELIABLE_UDP_ACK_SIZE = 1 + 4  # type, seq
K_RELIABLE_UDP_RETRANSMIT_MS = 50
K_RELIABLE_UDP_MAX_RETRIES = 5


class ReliableUDPClient:
    """Reliable UDP channel: seq, ack, retransmit. Matches C++ ReliableUDPChannel."""

    def __init__(self, sock, remote_addr, on_data_callback):
        self._sock = sock
        self._remote = remote_addr
        self._on_data = on_data_callback
        self._lock = threading.Lock()
        self._next_send_seq = 0
        self._pending = {}  # seq -> (packet, sent_at, retries)
        self._running = False
        self._retransmit_thread = None

    def start(self):
        self._running = True
        self._retransmit_thread = threading.Thread(target=self._retransmit_loop, daemon=True)
        self._retransmit_thread.start()

    def stop(self):
        self._running = False

    def send(self, data):
        """Send data with reliable delivery."""
        with self._lock:
            seq = self._next_send_seq
            self._next_send_seq += 1
            # Build packet: type(1) + seq(4) + len(2) + data
            header = struct.pack('<BIH', K_RELIABLE_UDP_DATA, seq, len(data))
            packet = header + data
            self._pending[seq] = (packet, time.time(), 0)
        self._send_packet(packet)

    def handle_received(self, buf):
        """Handle received raw UDP data."""
        if len(buf) < 1:
            return
        if buf[0] == K_RELIABLE_UDP_ACK:
            if len(buf) < K_RELIABLE_UDP_ACK_SIZE:
                return
            seq = struct.unpack_from('<I', buf, 1)[0]
            with self._lock:
                self._pending.pop(seq, None)
            return
        if buf[0] == K_RELIABLE_UDP_DATA and len(buf) >= K_RELIABLE_UDP_HEADER_SIZE:
            seq = struct.unpack_from('<I', buf, 1)[0]
            plen = struct.unpack_from('<H', buf, 5)[0]
            if len(buf) < K_RELIABLE_UDP_HEADER_SIZE + plen:
                return
            # Send ack
            ack = struct.pack('<BI', K_RELIABLE_UDP_ACK, seq)
            self._sock.sendto(ack, self._remote)
            # Deliver data
            payload = buf[K_RELIABLE_UDP_HEADER_SIZE:K_RELIABLE_UDP_HEADER_SIZE + plen]
            if self._on_data:
                self._on_data(payload)
            return

    def _send_packet(self, packet):
        try:
            self._sock.sendto(packet, self._remote)
        except socket.error:
            pass

    def _retransmit_loop(self):
        while self._running:
            time.sleep(K_RELIABLE_UDP_RETRANSMIT_MS / 1000.0)
            now = time.time()
            with self._lock:
                for seq in list(self._pending.keys()):
                    packet, sent_at, retries = self._pending[seq]
                    elapsed = (now - sent_at) * 1000
                    if elapsed >= K_RELIABLE_UDP_RETRANSMIT_MS:
                        if retries >= K_RELIABLE_UDP_MAX_RETRIES:
                            del self._pending[seq]
                            continue
                        self._send_packet(packet)
                        self._pending[seq] = (packet, now, retries + 1)


class FrameSyncUDPClient:
    """UDP-based frame sync client with reliable delivery.
    
    Connects to C++ asio_server_engine via UDP, using the same reliable layer.
    """

    def __init__(self, host, port, controlled_slots_callback=None):
        self.host = host
        self.port = port
        self.controlled_slots_callback = controlled_slots_callback or (lambda: [])
        self._sock = None
        self._remote = None
        self._channel = None
        self._lock = threading.Lock()
        self._recv_buf = bytearray()
        self._auth_frame_queue = collections.deque()
        self._session_start = None
        self._slot_assignment = None
        self._last_state_hash = None
        self._running = False
        self._recv_thread = None
        self._last_auth_frame_id = -1
        self._frames_without_packet = 0
        self._disconnect_after_frames = 30
        self._disconnected = False
        self._last_heartbeat_ms = 0
        self._heartbeat_miss_count = 0
        self._send_timestamps = {}
        self._rtt_samples = collections.deque(maxlen=50)
        self._last_rtt_ms = 0.0
        self._avg_rtt_ms = 0.0

    def connect(self):
        """Connect to UDP server and wait for SessionStart + SlotAssignment."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._remote = (self.host, self.port)
        self._running = True
        self._last_heartbeat_ms = int(time.time() * 1000)
        self._heartbeat_miss_count = 0

        # Create reliable channel
        self._channel = ReliableUDPClient(
            self._sock, self._remote, self._on_reliable_data)
        self._channel.start()

        # Send version negotiate
        ver_data = pack_version_negotiate()
        self._channel.send(ver_data)

        # Start receive thread
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # Wait for SessionStart + SlotAssignment
        for _ in range(100):
            with self._lock:
                if self._session_start is not None and self._slot_assignment is not None:
                    break
            time.sleep(0.05)
        with self._lock:
            if self._session_start is None or self._slot_assignment is None:
                raise RuntimeError('Did not receive SessionStart and SlotAssignment')
        return self._session_start, self._slot_assignment

    def _on_reliable_data(self, data):
        """Called by ReliableUDPClient when reliable data is received."""
        with self._lock:
            self._recv_buf.extend(data)
            while True:
                msg_type, payload = self._parse_one_message()
                if payload is None:
                    break
                if msg_type == MessageType.AuthoritativeFrame:
                    self._auth_frame_queue.append(payload)
                    self._last_auth_frame_id = payload[0]
                    self._frames_without_packet = 0
                    auth_fid = payload[0]
                    if auth_fid in self._send_timestamps:
                        rtt = (time.time() - self._send_timestamps.pop(auth_fid)) * 1000.0
                        self._rtt_samples.append(rtt)
                        self._last_rtt_ms = rtt
                        if self._rtt_samples:
                            self._avg_rtt_ms = sum(self._rtt_samples) / len(self._rtt_samples)
                elif msg_type == MessageType.Heartbeat:
                    self._last_heartbeat_ms = int(time.time() * 1000)
                    self._heartbeat_miss_count = 0
                elif msg_type == MessageType.StateHash:
                    self._last_state_hash = payload
                elif msg_type == MessageType.SessionStart:
                    self._session_start = payload
                elif msg_type == MessageType.SlotAssignment:
                    self._slot_assignment = payload

    def _parse_one_message(self):
        if len(self._recv_buf) < 1:
            return None, None
        msg_type = self._recv_buf[0]
        if msg_type == MessageType.Heartbeat:
            if len(self._recv_buf) < HEARTBEAT_BYTES:
                return None, None
            data = bytes(self._recv_buf[:HEARTBEAT_BYTES])
            del self._recv_buf[:HEARTBEAT_BYTES]
            try:
                frame_id, ts = unpack_heartbeat(data)
                return msg_type, (frame_id, ts)
            except ValueError:
                return None, None
        if msg_type == MessageType.AuthoritativeFrame:
            if len(self._recv_buf) < 7:
                return None, None
            num_slots = struct.unpack_from('<H', self._recv_buf, 5)[0]
            need = 7 + num_slots * SLOT_INPUT_BYTES
            if len(self._recv_buf) < need:
                return None, None
            data = bytes(self._recv_buf[:need])
            del self._recv_buf[:need]
            try:
                frame_id, slot_inputs = unpack_authoritative_frame(data)
                return msg_type, (frame_id, slot_inputs)
            except ValueError:
                return None, None
        if msg_type == MessageType.SessionStart:
            from gfootball.frame_sync.protocol import SESSION_START_PAYLOAD_BYTES
            need = 1 + SESSION_START_PAYLOAD_BYTES
            if len(self._recv_buf) < need:
                return None, None
            data = bytes(self._recv_buf[:need])
            del self._recv_buf[:need]
            try:
                seed, left, right = unpack_session_start(data)
                return msg_type, (seed, left, right)
            except ValueError:
                return None, None
        if msg_type == MessageType.SlotAssignment:
            if len(self._recv_buf) < 1 + 2:
                return None, None
            num = struct.unpack_from('<H', self._recv_buf, 1)[0]
            need = 1 + 2 + num * 2
            if len(self._recv_buf) < need:
                return None, None
            data = bytes(self._recv_buf[:need])
            del self._recv_buf[:need]
            try:
                slots = unpack_slot_assignment(data)
                return msg_type, slots
            except ValueError:
                return None, None
        if msg_type == MessageType.StateHash:
            if len(self._recv_buf) < STATE_HASH_BYTES:
                return None, None
            data = bytes(self._recv_buf[:STATE_HASH_BYTES])
            del self._recv_buf[:STATE_HASH_BYTES]
            try:
                return msg_type, unpack_state_hash(data)
            except ValueError:
                return None, None
        return None, None

    def _recv_loop(self):
        while self._running and self._sock:
            try:
                data, addr = self._sock.recvfrom(4096)
                if self._channel:
                    self._channel.handle_received(data)
            except socket.error:
                pass
            time.sleep(0.001)

    def send_ready(self):
        if self._channel:
            self._channel.send(pack_ready())

    def send_frame_input(self, frame_id):
        entries = self.controlled_slots_callback()
        if not entries:
            return
        if self._channel:
            data = pack_client_frame_input(frame_id, entries)
            self._channel.send(data)
            with self._lock:
                self._send_timestamps[frame_id] = time.time()

    def pop_authoritative_frame(self):
        with self._lock:
            if not self._auth_frame_queue:
                return None
            self._frames_without_packet = 0
            return self._auth_frame_queue.popleft()

    def has_authoritative_frame(self):
        with self._lock:
            return len(self._auth_frame_queue) > 0

    def tick_disconnect_detection(self):
        with self._lock:
            if not self._auth_frame_queue:
                self._frames_without_packet += 1
            if self._frames_without_packet >= self._disconnect_after_frames:
                self._disconnected = True
            now_ms = int(time.time() * 1000)
            if self._last_heartbeat_ms > 0:
                elapsed = now_ms - self._last_heartbeat_ms
                expected_misses = elapsed // HEARTBEAT_INTERVAL_MS
                if expected_misses > self._heartbeat_miss_count:
                    self._heartbeat_miss_count = expected_misses
                if self._heartbeat_miss_count >= HEARTBEAT_MISS_LIMIT:
                    self._disconnected = True

    def is_disconnected(self):
        with self._lock:
            return self._disconnected

    def pop_state_hash(self):
        with self._lock:
            out = self._last_state_hash
            self._last_state_hash = None
            return out

    def check_state_hash(self, frame_id, local_state_str):
        h = self.pop_state_hash()
        if h is None:
            return True
        fid, server_hash = h
        if fid != frame_id:
            return True
        local_hash = compute_state_hash(
            local_state_str if isinstance(local_state_str, bytes) else local_state_str.encode()
        )
        return local_hash == server_hash

    def close(self):
        self._running = False
        if self._channel:
            self._channel.stop()
        if self._sock:
            try:
                self._sock.close()
            except socket.error:
                pass
            self._sock = None

    def get_rtt_ms(self):
        return self._last_rtt_ms

    def get_avg_rtt_ms(self):
        return self._avg_rtt_ms

    def get_rtt_samples(self):
        return list(self._rtt_samples)

    def get_input_latency_ms(self):
        return self._avg_rtt_ms / 2.0

    def reset_for_reconnect(self):
        with self._lock:
            if self._channel:
                self._channel.stop()
            self._sock = None
            self._channel = None
            self._recv_buf = bytearray()
            self._auth_frame_queue.clear()
            self._session_start = None
            self._slot_assignment = None
            self._last_state_hash = None
            self._last_auth_frame_id = -1
            self._frames_without_packet = 0
            self._disconnected = False
            self._last_heartbeat_ms = 0
            self._heartbeat_miss_count = 0


def _build_frame_input_buffer(slot_inputs):
    buf = bytearray()
    for s in slot_inputs:
        from gfootball.frame_sync.protocol import pack_slot_input
        buf.extend(pack_slot_input(s))
    return bytes(buf)


class ReconnectingFrameSyncUDPClient:
    """断线重连包装器（UDP版本）：检测断连后以指数退避自动重连。
    
    用法:
        rclient = ReconnectingFrameSyncUDPClient(host, port, callback)
        session, slots = rclient.connect()  # 首次连接
        # ... 帧循环中 ...
        rclient.tick()  # 检测断连并自动重连
        if rclient.is_reconnecting:
            print('重连中...')
    """

    def __init__(self, host, port, controlled_slots_callback=None):
        self.host = host
        self.port = port
        self.controlled_slots_callback = controlled_slots_callback
        self._client = FrameSyncUDPClient(host, port, controlled_slots_callback)
        self._reconnecting = False
        self._reconnect_attempts = 0
        self._next_reconnect_ms = 0
        self._on_reconnect_callback = None
        self._on_disconnect_callback = None
        self._on_give_up_callback = None

    def set_on_reconnect(self, callback):
        """设置重连成功回调：callback(session_start, slot_assignment)。"""
        self._on_reconnect_callback = callback

    def set_on_disconnect(self, callback):
        """设置断连回调：callback()。"""
        self._on_disconnect_callback = callback

    def set_on_give_up(self, callback):
        """设置放弃重连回调：callback()。"""
        self._on_give_up_callback = callback

    def connect(self):
        """首次连接。"""
        session, slots = self._client.connect()
        self._reconnecting = False
        self._reconnect_attempts = 0
        return session, slots

    def tick(self):
        """每帧调用：检测断连并自动重连。"""
        if not self._reconnecting:
            self._client.tick_disconnect_detection()
            if self._client.is_disconnected():
                self._start_reconnect()
            return

        now_ms = int(time.time() * 1000)
        if now_ms < self._next_reconnect_ms:
            return

        self._reconnect_attempts += 1
        max_attempts = RECONNECT_MAX_ATTEMPTS
        if max_attempts > 0 and self._reconnect_attempts > max_attempts:
            self._reconnecting = False
            if self._on_give_up_callback:
                self._on_give_up_callback()
            return

        try:
            self._client.reset_for_reconnect()
            self._client = FrameSyncUDPClient(self.host, self.port, self.controlled_slots_callback)
            session, slots = self._client.connect()
            self._reconnecting = False
            self._reconnect_attempts = 0
            if self._on_reconnect_callback:
                self._on_reconnect_callback(session, slots)
        except (socket.error, RuntimeError, OSError):
            delay_ms = min(
                RECONNECT_BASE_MS * (2 ** (self._reconnect_attempts - 1)),
                RECONNECT_MAX_MS,
            )
            self._next_reconnect_ms = now_ms + delay_ms

    def _start_reconnect(self):
        """开始重连流程。"""
        self._reconnecting = True
        self._reconnect_attempts = 0
        self._next_reconnect_ms = int(time.time() * 1000)
        if self._on_disconnect_callback:
            self._on_disconnect_callback()

    @property
    def client(self):
        """获取底层 FrameSyncUDPClient。"""
        return self._client

    @property
    def is_reconnecting(self):
        return self._reconnecting

    @property
    def reconnect_attempts(self):
        return self._reconnect_attempts

    def close(self):
        self._reconnecting = False
        self._client.close()
