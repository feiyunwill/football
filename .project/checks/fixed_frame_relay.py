"""Bounded TCP test relay: forward actual server bytes through frame 20's hash.

This is a fixture boundary, not a production match-end protocol. No authority,
hash or input is synthesized. Later server traffic remains behind backpressure.
"""
import select
import socket
import struct
import threading
import time


def require(value, message):
    if not value:
        raise RuntimeError(message)


class FixedFrameRelay:
    FRAMES = 21
    CAPACITY = 8192

    def __init__(self, upstream_port):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.setblocking(False)
        self.port = self.listener.getsockname()[1]
        self.upstream_port = upstream_port
        self.stopping = threading.Event()
        self.reached = threading.Event()
        self.errors = []
        self.frames = 0
        self.hashes = 0
        self.authority = bytearray()
        self.hash_packets = bytearray()
        self.cutoff = False
        self.thread = threading.Thread(target=self._run, name='football-fixed-frame-relay')
        self.thread.start()

    def packet(self, data):
        """Return one bounded, validated server packet length, or zero if partial."""
        if not data:
            return 0
        kind = data[0]
        lengths = {5: 9, 7: 5, 3: 27, 4: 13, 8: 9, 10: 7, 11: 7}
        require(kind in lengths, 'Unexpected server message in fixed fixture')
        length = lengths[kind]
        if len(data) < length:
            return 0
        if kind == 5:
            require(struct.unpack('<BIHH', data[:length]) == (5, 42, 1, 1), 'Session differs')
        elif kind == 7:
            _, count, slot = struct.unpack('<BHH', data[:length])
            require(count == 1 and slot < 2, 'Invalid actual slot assignment')
        elif kind == 3:
            _, frame, slots = struct.unpack('<BIH', data[:7])
            require(frame == self.frames and slots == 2 and frame < self.FRAMES,
                    'Noncontiguous or excessive authority')
            self.frames += 1
            self.authority.extend(data[:length])
        elif kind == 4:
            _, frame, _ = struct.unpack('<BIQ', data[:length])
            require(frame == self.hashes * 10 and frame < self.frames, 'Unexpected server hash order')
            self.hashes += 1
            self.hash_packets.extend(data[:length])
            if frame == self.FRAMES - 1:
                require(self.frames == self.FRAMES and self.hashes == 3, 'Incomplete fixed boundary')
                self.cutoff = True
        return length

    def _run(self):
        peer = upstream = None
        try:
            deadline = time.monotonic() + 45
            while not self.stopping.is_set() and peer is None:
                require(time.monotonic() < deadline, 'Client accept deadline')
                if select.select([self.listener], [], [], 0.02)[0]:
                    peer = self.listener.accept()[0]
            if peer is None:
                return
            upstream = socket.create_connection(('127.0.0.1', self.upstream_port), timeout=5)
            peer.setblocking(False)
            upstream.setblocking(False)
            received, to_peer, to_server = bytearray(), bytearray(), bytearray()
            while not self.stopping.is_set():
                require(time.monotonic() < deadline, 'Relay deadline')
                if not self.cutoff and not to_peer:
                    length = self.packet(received)
                    if length:
                        to_peer.extend(received[:length])
                        del received[:length]
                if self.cutoff and not to_peer:
                    self.reached.set()
                readers = []
                if len(to_server) < self.CAPACITY:
                    readers.append(peer)
                if not self.cutoff and len(received) < self.CAPACITY:
                    readers.append(upstream)
                writers = ([peer] if to_peer else []) + ([upstream] if to_server else [])
                ready, writable, _ = select.select(readers, writers, [], 0.02)
                for source in ready:
                    destination = to_server if source is peer else received
                    try:
                        block = source.recv(self.CAPACITY - len(destination))
                    except BlockingIOError:
                        continue
                    require(block, 'Unexpected EOF before fixture closure')
                    destination.extend(block)
                for target in writable:
                    pending = to_peer if target is peer else to_server
                    try:
                        count = target.send(pending)
                    except BlockingIOError:
                        continue
                    require(count > 0, 'Relay send made no progress')
                    del pending[:count]
                require(max(len(received), len(to_peer), len(to_server)) <= self.CAPACITY,
                        'Relay exceeded its buffer capacity')
        except Exception as error:
            if not self.stopping.is_set():
                self.errors.append(str(error))
        finally:
            for owned in (peer, upstream, self.listener):
                if owned is not None:
                    owned.close()

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=6)
        require(not self.thread.is_alive(), 'Owned relay thread failed to stop')


class ProductWireRelay:
    """Forward actual product TCP bytes and retain the first 21 authority frames."""
    FRAMES = 21
    CAPACITY = 8192
    CAPTURE_LIMIT = 512 * 1024

    def __init__(self, upstream_port):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.setblocking(False)
        self.port = self.listener.getsockname()[1]
        self.upstream_port = upstream_port
        self.stopping = threading.Event()
        self.errors = []
        self.captured = bytearray()
        self.cutoff = False
        self.authority = bytearray()
        self.hash_packets = bytearray()
        self.frames = 0
        self.hashes = 0
        self.thread = threading.Thread(target=self._run, name='football-product-wire-relay')
        self.thread.start()

    def _run(self):
        peer = upstream = None
        try:
            deadline = time.monotonic() + 45
            while not self.stopping.is_set() and peer is None:
                require(time.monotonic() < deadline, 'Product client accept deadline')
                if select.select([self.listener], [], [], .02)[0]:
                    peer = self.listener.accept()[0]
            if peer is None:
                return
            upstream = socket.create_connection(('127.0.0.1', self.upstream_port), timeout=5)
            peer.setblocking(False)
            upstream.setblocking(False)
            to_peer, to_server, received = bytearray(), bytearray(), bytearray()
            while not self.stopping.is_set():
                require(time.monotonic() < deadline, 'Product relay deadline')
                while not self.cutoff:
                    length = self.packet_length(received)
                    if not length:
                        break
                    packet = bytes(received[:length])
                    del received[:length]
                    require(len(self.captured) + length <= self.CAPTURE_LIMIT,
                            'Product wire capture exceeded bound')
                    self.captured.extend(packet)
                    to_peer.extend(packet)
                    if packet[0] == 4 and struct.unpack_from('<I', packet, 1)[0] == self.FRAMES - 1:
                        self.cutoff = True
                readers = []
                if len(to_server) < self.CAPACITY:
                    readers.append(peer)
                if not self.cutoff and len(received) < self.CAPACITY:
                    readers.append(upstream)
                writers = ([peer] if to_peer else []) + ([upstream] if to_server else [])
                ready, writable, _ = select.select(readers, writers, [], .02)
                for source in ready:
                    block = source.recv(self.CAPACITY)
                    if not block:
                        return
                    if source is upstream:
                        received.extend(block)
                    else:
                        to_server.extend(block)
                for target in writable:
                    pending = to_peer if target is peer else to_server
                    count = target.send(pending)
                    require(count > 0, 'Product relay send made no progress')
                    del pending[:count]
                require(max(len(to_peer), len(to_server), len(received)) <= self.CAPACITY,
                        'Product relay exceeded forwarding bound')
        except Exception as error:
            if not self.stopping.is_set():
                self.errors.append(str(error))
        finally:
            for owned in (peer, upstream, self.listener):
                if owned is not None:
                    owned.close()

    @staticmethod
    def packet_length(data, offset=0):
        if offset >= len(data):
            return 0
        kind = data[offset]
        remaining = len(data) - offset
        if 80 <= kind <= 92:
            if remaining < 10:
                return 0
            require(data[offset + 1:offset + 8] == b'FNRC\x01\0\0',
                    'Invalid product recovery header')
            length = 10 + struct.unpack_from('<H', data, offset + 8)[0]
            require(length <= 1100, 'Unbounded product recovery record')
        elif kind in (66, 4, 8, 10, 11):
            length = {66: 32, 4: 13, 8: 9, 10: 7, 11: 7}[kind]
        elif kind in (3, 7):
            prefix = 7 if kind == 3 else 3
            if remaining < prefix:
                return 0
            count = struct.unpack_from('<H', data, offset + (5 if kind == 3 else 1))[0]
            require(0 < count <= 22, 'Unbounded product wire slot count')
            length = prefix + count * (10 if kind == 3 else 2)
        else:
            raise RuntimeError('Unexpected product server packet ' + str(kind))
        return length if remaining >= length else 0

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=6)
        require(not self.thread.is_alive() and not self.errors,
                'Product relay failed: ' + str(self.errors))
        data = self.captured
        offset = 0
        while offset < len(data):
            kind = data[offset]
            length = self.packet_length(data, offset)
            require(length, 'Incomplete product server packet')
            packet = data[offset:offset + length]
            if kind == 3 and self.frames < self.FRAMES:
                frame, slots = struct.unpack_from('<IH', packet, 1)
                require(frame == self.frames and slots == 2, 'Noncontiguous product authority')
                self.authority.extend(packet)
                self.frames += 1
            elif kind == 4 and self.hashes < 3:
                frame = struct.unpack_from('<I', packet, 1)[0]
                require(frame == self.hashes * 10, 'Unexpected product hash order')
                self.hash_packets.extend(packet)
                self.hashes += 1
            offset += length
        require(self.frames == self.FRAMES and self.hashes == 3,
                'Incomplete product authority prefix')
        require(self.cutoff, 'Product fixture boundary was not reached')
