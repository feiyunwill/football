#!/usr/bin/env python3
"""Actual standalone TCP server: wire progress, malformed input and clean shutdown.

This probe does not claim GameEnv determinism or integrated TCP client coverage.
The slow-reader stress contract lives in tcp_frame_server_test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import struct
import subprocess
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unused_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def exact(peer, length):
    result = b''
    while len(result) < length:
        chunk = peer.recv(length - len(result))
        if not chunk:
            raise AssertionError('unexpected EOF')
        result += chunk
    return result


def clean(log):
    return not any(marker in log for marker in (
        'ERROR: AddressSanitizer', 'ERROR: LeakSanitizer', 'runtime error:',
        'AddressSanitizer:DEADLYSIGNAL', 'SUMMARY: UndefinedBehaviorSanitizer'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.server = args.server.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(ASAN_OPTIONS='halt_on_error=1:detect_leaks=1:quarantine_size_mb=16',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1', LSAN_OPTIONS='exitcode=23')
    rows = []
    for name, cli in (
        ('zero_slots', [str(unused_port()), '0', '0', '42']),
        ('narrowing_wrap', [str(unused_port()), '65537', '0', '42']),
        ('trailing_text', [str(unused_port()), '1junk', '0', '42']),
        ('seed_overflow', [str(unused_port()), '1', '0', '4294967296']),
        ('invalid_port', ['0'])):
        result = subprocess.run([str(args.server), *cli], env=env, capture_output=True, text=True, timeout=5)
        log = args.output / (name + '.log')
        log.write_text(result.stdout + result.stderr)
        rows.append(dict(case=name, exit_code=result.returncode,
                         passed=result.returncode == 1 and 'failed:' in log.read_text() and clean(log.read_text()),
                         log_sha256=sha(log)))
    for name in ('normal_progress_shutdown', 'oversized_header_shutdown'):
        port = unused_port()
        log_path = args.output / (name + '.log')
        details = dict(case=name, passed=False)
        with log_path.open('w') as output:
            process = subprocess.Popen([str(args.server), str(port), '1', '0', '42'],
                                       env=env, stdout=output, stderr=subprocess.STDOUT)
            peer = None
            try:
                deadline = time.monotonic() + 5
                while 'listening on port' not in log_path.read_text():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise AssertionError('server did not report listening')
                    time.sleep(0.01)
                peer = socket.create_connection(('127.0.0.1', port), timeout=3)
                assert struct.unpack('<BIHH', exact(peer, 9)) == (5, 42, 1, 0)
                assert struct.unpack('<BHH', exact(peer, 5)) == (7, 1, 0)
                if name == 'oversized_header_shutdown':
                    peer.sendall(b'\x06' + struct.pack('<BIH', 2, 0, 65535))
                    assert peer.recv(1) == b'', 'malformed peer was not closed'
                    details['header_rejected_without_payload'] = True
                else:
                    peer.sendall(b'\x06')
                    buffered = b''
                    received = []
                    for frame in range(3):
                        # SlotInput is packed to 10 bytes (protocol.hpp static_assert).
                        value = struct.pack('<ffH', 0.25 * (frame + 1), -0.25, 0)
                        packet = struct.pack('<BIHH', 2, frame, 1, 0) + value
                        deadline = time.monotonic() + 3
                        while len(buffered) < 17:
                            if time.monotonic() >= deadline:
                                raise AssertionError('authority stopped progressing')
                            peer.sendall(packet)
                            readable, _, _ = select.select([peer], [], [], 0.02)
                            if readable:
                                chunk = peer.recv(4096)
                                assert chunk, 'unexpected EOF during match'
                                buffered += chunk
                        authority, buffered = buffered[:17], buffered[17:]
                        assert struct.unpack('<BIH', authority[:7]) == (3, frame, 1)
                        assert authority[7:] == value, f'input mismatch at frame {frame}: expected={value.hex()}, actual={authority[7:].hex()}'
                        received.append(frame)
                    details['consecutive_full_authority_frames'] = received
                    details['preserved_input_bytes'] = True
                # Keep the connected peer alive through server teardown.
                process.send_signal(signal.SIGTERM)
                details['exit_code'] = process.wait(timeout=5)
                details['passed'] = details['exit_code'] == 0
            except Exception as error:
                details['error'] = str(error)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                    details['forced_cleanup'] = True
                if peer is not None:
                    peer.close()
        details['sanitizers_clean'] = clean(log_path.read_text())
        details['passed'] &= details['sanitizers_clean']
        details['log_sha256'] = sha(log_path)
        rows.append(details)
    report = dict(scope='standalone TCP executable; excludes GameEnv and integrated TCP clients',
                  binary=str(args.server), binary_sha256=sha(args.server),
                  sources={str(path): sha(path) for path in (
                      Path('engine/src/frame_sync/asio_server.cpp'),
                      Path('engine/src/frame_sync/tcp_frame_server.hpp'),
                      Path('engine/src/frame_sync/bounded_tcp_writer.hpp'),
                      Path(__file__).resolve())},
                  passed=all(row['passed'] for row in rows), cases=rows)
    destination = args.output / 'report.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
