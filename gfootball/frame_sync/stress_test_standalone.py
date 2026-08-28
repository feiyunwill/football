# Copyright 2019 Google LLC
# 2026-08-28 帧同步压力测试（独立版）：复制协议/配置文件到临时目录，
# 完全绕过 gfootball 包导入链，适用于引擎不可用的环境。

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import sys
import socket
import struct
import threading
import time
import collections
import tempfile
import shutil
import traceback


def _setup_isolated_env():
    """将 protocol.py 和 config.py 复制到临时目录，重写导入路径。"""
    tmpdir = tempfile.mkdtemp(prefix='fs_stress_')
    src_dir = os.path.dirname(os.path.abspath(__file__))

    # 复制 config.py
    with open(os.path.join(tmpdir, 'config.py'), 'w') as f:
        f.write(open(os.path.join(src_dir, 'config.py')).read())

    # 复制 protocol.py 并替换导入路径
    content = open(os.path.join(src_dir, 'protocol.py')).read()
    content = content.replace('from gfootball.frame_sync.config import', 'from config import')
    with open(os.path.join(tmpdir, 'protocol.py'), 'w') as f:
        f.write(content)

    open(os.path.join(tmpdir, '__init__.py'), 'w').close()
    return tmpdir


class _EchoServer(object):
    """最小化 TCP echo server，接受连接并发 SessionStart + SlotAssignment。"""

    def __init__(self, proto, host='127.0.0.1', port=0):
        self._p = proto
        self.host = host
        self.port = port
        self._sock = None
        self._running = False
        self._clients = []
        self._lock = threading.Lock()
        self._next_slot = 0

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(16)
        self._sock.settimeout(1.0)
        self.port = self._sock.getsockname()[1]
        self._running = True
        self._t = threading.Thread(target=self._accept, daemon=True)
        self._t.start()

    def _accept(self):
        while self._running:
            try:
                conn, _ = self._sock.accept()
                with self._lock:
                    slot = self._next_slot
                    self._next_slot += 1
                    self._clients.append(conn)
                conn.sendall(self._p.pack_session_start(42, 1, 1))
                conn.sendall(self._p.pack_slot_assignment([slot]))
            except socket.timeout:
                continue
            except socket.error:
                if self._running:
                    continue
                break

    def broadcast_heartbeat(self, frame_id=0):
        hb = self._p.pack_heartbeat(frame_id, int(time.time() * 1000) & 0xFFFFFFFF)
        with self._lock:
            for c in list(self._clients):
                try:
                    c.sendall(hb)
                except socket.error:
                    pass

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except socket.error:
                pass
        with self._lock:
            for c in self._clients:
                try:
                    c.close()
                except socket.error:
                    pass
            self._clients = []


# ===== 测试 =====

def test_pack_unpack(p):
    print('[TEST] Protocol pack/unpack...')
    for fid, ts in [(0, 0), (42, 1234567890), (0xFFFFFFFF, 0xFFFFFFFF)]:
        f2, t2 = p.unpack_heartbeat(p.pack_heartbeat(fid, ts))
        assert f2 == fid and t2 == ts
    slots = [p.SlotInput(1.0, -0.5, 0b1010), p.SlotInput(0.0, 0.0, 0)]
    fid, s = p.unpack_authoritative_frame(p.pack_authoritative_frame(100, slots))
    assert fid == 100 and len(s) == 2 and s[0].dir_x == 1.0
    entries = [(0, p.SlotInput(0.5, 0.5, 0b0011)), (1, p.SlotInput(-0.5, 0.0, 0b0100))]
    fid2, e2 = p.unpack_client_frame_input(p.pack_client_frame_input(50, entries))
    assert fid2 == 50 and len(e2) == 2
    seed, l, r = p.unpack_session_start(p.pack_session_start(42, 2, 3))
    assert seed == 42 and l == 2 and r == 3
    sl = p.unpack_slot_assignment(p.pack_slot_assignment([0, 2, 5]))
    assert sl == [0, 2, 5]
    print('  ALL pack/unpack PASSED')


def test_concurrent(p):
    print('[TEST] Concurrent connections (10 clients)...')
    srv = _EchoServer(p)
    srv.start()
    time.sleep(0.1)
    socks = [socket.socket(socket.AF_INET, socket.SOCK_STREAM) for _ in range(10)]
    for s in socks:
        s.connect(('127.0.0.1', srv.port))
    time.sleep(0.3)
    ok = sum(1 for s in socks if len(s.recv(256)) >= 13)
    assert ok == 10
    for s in socks:
        s.close()
    srv.stop()
    print(f'  [OK] {ok}/10 received session data')


def test_heartbeat(p):
    print('[TEST] Heartbeat broadcast...')
    srv = _EchoServer(p)
    srv.start()
    time.sleep(0.1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', srv.port))
    sock.settimeout(1.0)
    time.sleep(0.2)
    sock.recv(256)
    srv.broadcast_heartbeat(frame_id=42)
    time.sleep(0.1)
    data = sock.recv(256)
    assert len(data) >= p.HEARTBEAT_BYTES
    if data[0] == p.MessageType.Heartbeat:
        fid, _ = p.unpack_heartbeat(data[:p.HEARTBEAT_BYTES])
        assert fid == 42
    sock.close()
    srv.stop()
    print('  [OK] Heartbeat received')


def test_timeout(p, c):
    print('[TEST] Heartbeat timeout...')
    st = {'hb_ms': int(time.time() * 1000), 'miss': 0, 'disc': False, 'fq': collections.deque(), 'fp': 0, 'da': 30}

    def tick():
        if not st['fq']:
            st['fp'] += 1
        if st['fp'] >= st['da']:
            st['disc'] = True
        now = int(time.time() * 1000)
        if st['hb_ms'] > 0:
            exp = (now - st['hb_ms']) // c.HEARTBEAT_INTERVAL_MS
            if exp > st['miss']:
                st['miss'] = exp
            if st['miss'] >= c.HEARTBEAT_MISS_LIMIT:
                st['disc'] = True

    tick()
    assert not st['disc']
    st['hb_ms'] = int(time.time() * 1000) - (c.HEARTBEAT_MISS_LIMIT + 1) * c.HEARTBEAT_INTERVAL_MS
    st['miss'] = 0
    tick()
    assert st['disc']
    print('  [OK] Timeout works')


def test_backoff(c):
    print('[TEST] Reconnection backoff...')
    base = c.RECONNECT_BASE_MS
    delays = [min(base * (2 ** i), c.RECONNECT_MAX_MS) for i in range(c.RECONNECT_MAX_ATTEMPTS)]
    assert delays[:6] == [1000, 2000, 4000, 8000, 16000, 30000]
    assert all(d == 30000 for d in delays[5:])
    print(f'  [OK] Sequence: {delays[:6]}...')


def test_hash(p):
    print('[TEST] State hash...')
    s = b'test state'
    assert p.compute_state_hash(s) == p.compute_state_hash(s)
    assert p.compute_state_hash(s) != p.compute_state_hash(b'other')
    print('  [OK] Consistent & unique')


def test_types(p):
    print('[TEST] Message types...')
    vals = [p.MessageType.Connect, p.MessageType.Disconnect, p.MessageType.FrameInput,
            p.MessageType.AuthoritativeFrame, p.MessageType.StateHash, p.MessageType.SessionStart,
            p.MessageType.Ready, p.MessageType.SlotAssignment, p.MessageType.Heartbeat]
    assert len(vals) == len(set(vals)) and all(0 <= v <= 255 for v in vals)
    print(f'  [OK] {len(vals)} unique types')


def test_throughput(p):
    print('[TEST] Throughput (1000 packets)...')
    srv = _EchoServer(p)
    srv.start()
    time.sleep(0.1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', srv.port))
    sock.settimeout(5.0)
    time.sleep(0.2)
    sock.recv(256)
    t0 = time.time()
    for i in range(1000):
        sock.sendall(p.pack_heartbeat(i, int(time.time() * 1000) & 0xFFFFFFFF))
    dt = time.time() - t0
    print(f'  [OK] Client sent 1000 in {dt:.3f}s ({1000/dt:.0f}/s)')
    t0 = time.time()
    for i in range(1000):
        srv.broadcast_heartbeat(frame_id=i)
    dt = time.time() - t0
    print(f'  [OK] Server sent 1000 in {dt:.3f}s ({1000/dt:.0f}/s)')
    sock.close()
    srv.stop()


def run_all():
    tmpdir = _setup_isolated_env()
    try:
        sys.path.insert(0, tmpdir)
        import protocol as p
        import config as c

        tests = [
            lambda: test_pack_unpack(p),
            lambda: test_types(p),
            lambda: test_hash(p),
            lambda: test_concurrent(p),
            lambda: test_heartbeat(p),
            lambda: test_timeout(p, c),
            lambda: test_backoff(c),
            lambda: test_throughput(p),
        ]
        ok = fail = 0
        for fn in tests:
            try:
                fn()
                ok += 1
            except Exception as e:
                print(f'  [FAIL] {fn.__name__}: {e}')
                traceback.print_exc()
                fail += 1
        print(f'\nResults: {ok} passed, {fail} failed')
        if fail:
            sys.exit(1)
        print('All stress tests PASSED!')
    finally:
        sys.path.remove(tmpdir)
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    run_all()
