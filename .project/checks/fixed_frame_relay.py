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
