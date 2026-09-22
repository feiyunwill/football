#!/usr/bin/env python3
"""Exercise actual GameEnv TCP executables, bounded client faults and two-player progress."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import time

from fixed_frame_relay import FixedFrameRelay

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(text):
    return not any(marker in text for marker in ('ERROR: AddressSanitizer', 'ERROR: LeakSanitizer',
        'runtime error:', 'AddressSanitizer:DEADLYSIGNAL', 'SUMMARY: UndefinedBehaviorSanitizer'))


def exact(peer, size):
    data = b''
    while len(data) < size:
        chunk = peer.recv(size - len(data))
        if not chunk:
            raise AssertionError('unexpected handshake EOF')
        data += chunk
    return data


def telemetry(text):
    match = re.search(r'TCP session confirmed=(\d+) verified_hashes=(\d+) failed=(\d+)', text)
    return dict(zip(('confirmed', 'verified_hashes', 'failed'), map(int, match.groups()))) if match else {}


def environment(build):
    env = os.environ.copy()
    for key in ('DISPLAY', 'LD_PRELOAD', 'SDL_VIDEODRIVER', 'GFOOTBALL_FONT'):
        env.pop(key, None)
    env.update(LD_LIBRARY_PATH=str(build), LIBGL_ALWAYS_SOFTWARE='1',
               GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
               ASAN_OPTIONS='halt_on_error=1:detect_leaks=1:quarantine_size_mb=16',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1', LSAN_OPTIONS='exitcode=23')
    return env


def fake_case(build, output, name, env):
    directory = output / name
    directory.mkdir()
    log = directory / 'client.log'
    client = build / 'bin/football_client_tcp'
    details = dict(case=name, passed=False)
    with socket.socket() as listener, log.open('w') as stream:
        listener.bind(('127.0.0.1', 0)); listener.listen(); listener.settimeout(20)
        port = listener.getsockname()[1]
        process = subprocess.Popen([str(client), '127.0.0.1', str(port), '1', '1', '42', '--headless'],
                                   cwd=directory, env=env, stdout=stream, stderr=subprocess.STDOUT)
        try:
            with listener.accept()[0] as peer:
                peer.settimeout(20)
                if name == 'partial_handshake':
                    peer.sendall(b'\x05\x2a')
                    expected = 'Failed to connect'
                elif name == 'invalid_dimensions':
                    peer.sendall(struct.pack('<BIHH', 5, 42, 12, 1))
                    expected = 'Failed to connect'
                else:
                    peer.sendall(struct.pack('<BIHH', 5, 42, 1, 1))
                    assert exact(peer, 1) == b'\x00'
                    if name == 'duplicate_assignment':
                        peer.sendall(struct.pack('<BHHH', 7, 2, 0, 0))
                        expected = 'Failed to connect'
                    else:
                        peer.sendall(struct.pack('<BHH', 7, 1, 0))
                        assert exact(peer, 1) == b'\x06', 'Ready missing after actual GameEnv initialization'
                        default = struct.pack('<ffH', 0, 0, 0) * 2
                        authority = lambda frame: struct.pack('<BIH', 3, frame, 2) + default
                        if name == 'invalid_authority_count':
                            packet = struct.pack('<BIH', 3, 0, 65535)
                            expected = 'invalid or unexpected message'
                        elif name == 'invalid_authority_input':
                            packet = struct.pack('<BIH', 3, 0, 2) + struct.pack('<ffH', float('nan'), 0, 0) + default[:10]
                            expected = 'invalid or unexpected message'
                        elif name == 'authority_queue_full':
                            packet = b''.join(authority(i) for i in range(1025))
                            expected = 'authority queue capacity exceeded'
                        elif name == 'authority_window':
                            packet = authority(0x7fffffff)
                            expected = 'authority outside reconciliation window'
                        elif name == 'hash_queue_full':
                            packet = b''.join(struct.pack('<BIQ', 4, i, 0) for i in range(1025))
                            expected = 'hash queue capacity exceeded'
                        elif name == 'hash_mismatch':
                            packet = authority(0) + struct.pack('<BIQ', 4, 0, 0)
                            expected = 'state hash mismatch'
                        elif name == 'control_framing':
                            packet = (struct.pack('<BHI', 10, 1, 0) + struct.pack('<BHI', 11, 1, 0) +
                                      struct.pack('<BII', 8, 0, 0x00030201) + authority(0))
                            expected = 'connection closed or stream read failed'
                        else:
                            raise AssertionError('unknown fixture case')
                        peer.sendall(packet)
                        if name == 'control_framing':
                            time.sleep(0.3)
                            peer.shutdown(socket.SHUT_RDWR)
                details['exit_code'] = process.wait(timeout=20)
                text = log.read_text()
                details.update(telemetry=telemetry(text), sanitizers_clean=clean(text), expected_reason=expected)
                details['passed'] = process.returncode == 1 and expected in text and details['sanitizers_clean']
                if name in ('hash_mismatch', 'control_framing'):
                    details['passed'] &= details['telemetry'].get('confirmed', 0) >= 1
        except Exception as error:
            details['error'] = str(error)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5); details['forced_cleanup'] = True
    details['log_sha256'] = sha(log)
    return details


def pair_case(build, output, env, *, fixed=False):
    directory = output / 'two_actual_players'; directory.mkdir()
    paths = [directory / name for name in ('server.log', 'left.log', 'right.log')]
    streams = [path.open('w') for path in paths]
    processes = []
    details = dict(case='two_actual_players', passed=False)
    guard = None
    relays = []
    try:
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
        server = subprocess.Popen([str(build / 'bin/football_server_tcp'), str(port), '1', '1', '42'],
                                  cwd=ROOT, env=env, stdout=streams[0], stderr=subprocess.STDOUT)
        processes.append(server)
        deadline = time.monotonic() + 30
        while 'Integrated TCP server listening on port' not in paths[0].read_text():
            if server.poll() is not None or time.monotonic() > deadline:
                raise AssertionError('actual GameEnv server failed to start')
            time.sleep(0.02)
        # This bounded pending handshake holds the initial ready barrier until
        # both actual clients are connected and have initialized their engines.
        guard = socket.create_connection(('127.0.0.1', port), timeout=5)
        assert len(exact(guard, 9)) == 9
        for index in (1, 2):
            working = directory / f'player{index}'; working.mkdir()
            # 2026-09-13: the fixed replay fixture uses unchanged real server
            # packets; the original abrupt-disconnect case retains its direct path.
            client_port = port
            if fixed:
                relay = FixedFrameRelay(port)
                relays.append(relay)
                client_port = relay.port
            process = subprocess.Popen([str(build / 'bin/football_client_tcp'), '127.0.0.1', str(client_port), '1', '1', '42', '--headless'],
                                       cwd=working, env=env, stdout=streams[index], stderr=subprocess.STDOUT)
            processes.append(process)
        deadline = time.monotonic() + 25
        while not all('Connected! My slots:' in path.read_text() for path in paths[1:]):
            if any(process.poll() is not None for process in processes) or time.monotonic() > deadline:
                raise AssertionError('actual clients failed to initialize')
            time.sleep(0.02)
        guard.close(); guard = None
        if fixed:
            deadline = time.monotonic() + 25
            while not all(relay.reached.is_set() for relay in relays):
                if (any(process.poll() is not None for process in processes) or
                        any(relay.errors for relay in relays) or time.monotonic() > deadline):
                    raise AssertionError('Fixed authority boundary was not delivered: ' + str([r.errors for r in relays]))
                time.sleep(0.02)
        # Fixed observation interval; no early stopping based on good hashes.
        deadline = time.monotonic() + (2 if fixed else 6)
        while time.monotonic() < deadline:
            if any(process.poll() is not None for process in processes):
                raise AssertionError('a process stopped during the healthy interval')
            time.sleep(0.02)
        if fixed:
            for index, relay in enumerate(relays, 1):
                relay.close()
                if relay.errors:
                    raise AssertionError(str(relay.errors))
                (directory / f'authority{index}.bin').write_bytes(relay.authority)
                (directory / f'hashes{index}.bin').write_bytes(relay.hash_packets)
            # Both clients consume the same fixed prefix before the real server
            # is stopped. A delayed client fails the exact count check below.
            for process in processes[1:]:
                process.wait(timeout=20)
        server.send_signal(signal.SIGTERM)
        codes = [process.wait(timeout=20) for process in processes]
        logs = [path.read_text() for path in paths]
        states = [telemetry(text) for text in logs[1:]]
        details.update(exit_codes=codes, clients=states, sanitizers_clean=all(clean(text) for text in logs))
        details['passed'] = codes == [0, 1, 1] and details['sanitizers_clean']
        details['passed'] &= all(state.get('confirmed', 0) >= 12 and state.get('verified_hashes', 0) >= 2 for state in states)
        details['passed'] &= all('connection closed or stream read failed' in text and 'hash mismatch' not in text for text in logs[1:])
        replays = []
        for index in (1, 2):
            replay = directory / f'player{index}' / 'replay_42.bin'
            size = replay.stat().st_size if replay.exists() else 0
            replays.append(dict(size=size, sha256=sha(replay) if size else None))
        details['replay_prefixes'] = replays
        details['passed'] &= all(0 < row['size'] <= 32 * 1024 * 1024 for row in replays)
        if fixed:
            details['case'] = 'two_actual_players_fixed_boundary'
            details['fixed_frames'] = FixedFrameRelay.FRAMES
            details['passed'] &= all(state.get('confirmed') == FixedFrameRelay.FRAMES and
                                     state.get('verified_hashes') == 3 for state in states)
            details['passed'] &= replays[0] == replays[1]
            details['passed'] &= relays[0].authority == relays[1].authority and relays[0].hash_packets == relays[1].hash_packets
            details['wire'] = {path.name: sha(path) for path in directory.glob('*.bin')}
    except Exception as error:
        details['error'] = str(error)
    finally:
        if guard is not None:
            guard.close()
        for relay in relays:
            relay.close()
        for process in processes:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5); details['forced_cleanup'] = True
        for stream in streams:
            stream.close()
    details['logs'] = {path.name: sha(path) for path in paths}
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    pair_mode = parser.add_mutually_exclusive_group()
    pair_mode.add_argument('--pair-only', action='store_true')
    pair_mode.add_argument('--fixed-pair-only', action='store_true')
    args = parser.parse_args()
    build, output = args.build.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = environment(build)
    cases = []
    if not (args.pair_only or args.fixed_pair_only):
        for name in ('partial_handshake', 'invalid_dimensions', 'duplicate_assignment',
                     'invalid_authority_count', 'invalid_authority_input', 'authority_queue_full',
                     'authority_window', 'hash_queue_full', 'hash_mismatch', 'control_framing'):
            row = fake_case(build, output, name, env); cases.append(row); print(json.dumps(row), flush=True)
    row = pair_case(build, output, env, fixed=args.fixed_pair_only); cases.append(row); print(json.dumps(row), flush=True)
    paths = ['engine/src/frame_sync/integrated_client.cpp', 'engine/src/frame_sync/integrated_server.cpp',
             'engine/src/frame_sync/engine_tcp_server.hpp', 'engine/src/frame_sync/engine_tcp_bridge.hpp',
             'engine/src/frame_sync/bounded_tcp_writer.hpp', '.project/checks/integrated_tcp_probe.py',
             '.project/checks/fixed_frame_relay.py']
    report = dict(scope='actual GameEnv TCP executables; headless pair uses neutral keyboard input',
                  passed=all(case['passed'] for case in cases), cases=cases,
                  sources={path: sha(ROOT / path) for path in paths},
                  binaries={name: sha(build / path) for name, path in (
                      ('server', 'bin/football_server_tcp'), ('client', 'bin/football_client_tcp'),
                      ('engine', 'libfootball_engine.so'))})
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
