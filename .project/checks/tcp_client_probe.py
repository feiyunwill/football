#!/usr/bin/env python3
"""Bounded TCP diagnostic executable: real socket progress and failure shutdown.

This executable has no GameEnv. Engine confirmation and snapshot restoration are
verified separately by engine_tcp_client_contract, not by received packet counts.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import threading
import time

from tcp_capacity_probe import clean, exact, sha, unused_port


def wait_for(predicate, process, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if process.poll() is not None or time.monotonic() >= deadline:
            raise AssertionError('process exited or progress deadline expired')
        time.sleep(0.01)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True, type=Path)
    parser.add_argument('--server', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.client, args.server = args.client.resolve(), args.server.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(ASAN_OPTIONS='halt_on_error=1:detect_leaks=1:quarantine_size_mb=16',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1', LSAN_OPTIONS='exitcode=23')
    rows = []
    for name, cli in (
        ('port_zero', ['127.0.0.1', '0']),
        ('port_overflow', ['127.0.0.1', '65536']),
        ('trailing_text', ['127.0.0.1', '1junk']),
        ('slot_overflow', ['127.0.0.1', '1', '22']),
        ('extra_argument', ['127.0.0.1', '1', '0', 'extra'])):
        row = dict(case=name, passed=False)
        log = args.output / (name + '.log')
        try:
            result = subprocess.run([str(args.client), *cli], env=env, capture_output=True,
                                    text=True, timeout=5)
            log.write_text(result.stdout + result.stderr)
            row.update(exit_code=result.returncode, passed=result.returncode == 1 and
                       ('Invalid client argument' in log.read_text() or 'Usage:' in log.read_text()))
        except Exception as error:
            row['error'] = str(error)
            log.write_text(str(error))
        row['log_sha256'] = sha(log)
        row['passed'] &= clean(log.read_text())
        rows.append(row)

    for name in ('client_signal_shutdown', 'server_eof_shutdown'):
        row = dict(case=name, passed=False)
        client_log, server_log = [args.output / (name + suffix) for suffix in ('.client.log', '.server.log')]
        port = unused_port()
        processes = []
        with client_log.open('w') as client_output, server_log.open('w') as server_output:
            try:
                server = subprocess.Popen([str(args.server), str(port), '1', '0', '42'], env=env,
                                          stdout=server_output, stderr=subprocess.STDOUT)
                processes.append(server)
                wait_for(lambda: 'Frame sync server listening on port' in server_log.read_text(), server)
                client = subprocess.Popen([str(args.client), '127.0.0.1', str(port), '0'], env=env,
                                          stdout=client_output, stderr=subprocess.STDOUT)
                processes.append(client)
                wait_for(lambda: len(re.findall(r'TCP authority frame=(\d+)', client_log.read_text())) >= 5, client)
                if name == 'client_signal_shutdown':
                    client.send_signal(signal.SIGTERM)
                    row['client_exit'] = client.wait(timeout=5)
                    server.send_signal(signal.SIGTERM)
                    row['server_exit'] = server.wait(timeout=5)
                    assert row['client_exit'] == 0 and row['server_exit'] == 0
                else:
                    server.send_signal(signal.SIGTERM)
                    row['server_exit'] = server.wait(timeout=5)
                    row['client_exit'] = client.wait(timeout=5)
                    assert row['server_exit'] == 0 and row['client_exit'] == 1
                frames = [int(frame) for frame in re.findall(r'TCP authority frame=(\d+)', client_log.read_text())]
                assert len(frames) >= 5 and frames == list(range(len(frames))), frames
                assert 'no game simulation' in client_log.read_text()
                assert f'frames_received={len(frames)} ' in client_log.read_text()
                row.update(passed=True, consecutive_received_frames=frames)
            except Exception as error:
                row['error'] = str(error)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                        row.update(forced_cleanup=True, passed=False)
        row['detector_log_clean'] = all(clean(path.read_text()) for path in (client_log, server_log))
        row['passed'] &= row['detector_log_clean']
        row['logs'] = {path.name: sha(path) for path in (client_log, server_log)}
        rows.append(row)

    for name in ('partial_handshake', 'oversized_authority_header', 'wrong_expected_slot', 'control_framing'):
        row = dict(case=name, passed=False)
        log = args.output / (name + '.log')
        failures = []
        stop = threading.Event()
        with socket.socket() as listener, log.open('w') as output:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(5)

            def serve():
                try:
                    with listener.accept()[0] as peer:
                        peer.settimeout(3)
                        if name == 'partial_handshake':
                            peer.sendall(b'\x05\x2a')
                            stop.wait(8)
                            return
                        peer.sendall(struct.pack('<BIHH', 5, 42, 1, 0))
                        assert exact(peer, 1) == b'\x00'
                        peer.sendall(struct.pack('<BHH', 7, 1, 0))
                        if name == 'wrong_expected_slot':
                            assert peer.recv(1) == b'', 'client sent Ready for wrong slot'
                            return
                        assert exact(peer, 1) == b'\x06'
                        if name == 'oversized_authority_header':
                            peer.sendall(struct.pack('<BIH', 3, 0, 65535))
                            stop.wait(2)
                            return
                        # Payload bytes deliberately include valid message IDs.
                        peer.sendall(struct.pack('<BII', 8, 0x03040506, 0x0708090a) +
                                     struct.pack('<BHI', 10, 0, 0x03040506) +
                                     struct.pack('<BHI', 11, 0, 0x0708090a) +
                                     struct.pack('<BIHffH', 3, 0, 1, 0.5, -0.5, 0))
                        wait_for(lambda: 'TCP authority frame=0 ' in log.read_text(), process)
                        # Finish sending, then drain client output so FIN is not
                        # replaced by a reset due to unread FrameInput bytes.
                        peer.shutdown(socket.SHUT_WR)
                        while peer.recv(4096):
                            pass
                except Exception as error:
                    failures.append(str(error))

            process = subprocess.Popen([str(args.client), '127.0.0.1', str(listener.getsockname()[1]),
                                        '1' if name == 'wrong_expected_slot' else '0'], env=env,
                                       stdout=output, stderr=subprocess.STDOUT)
            thread = threading.Thread(target=serve)
            started = time.monotonic()
            thread.start()
            try:
                row['exit_code'] = process.wait(timeout=8 if name == 'partial_handshake' else 2)
                row['elapsed_seconds'] = time.monotonic() - started
                assert row['exit_code'] == 1
                if name == 'partial_handshake':
                    assert 'TCP handshake failed' in log.read_text()
                    assert 4.5 <= row['elapsed_seconds'] < 8
                elif name == 'wrong_expected_slot':
                    assert 'Assigned slot differs from EXPECTED_SLOT' in log.read_text()
                elif name == 'oversized_authority_header':
                    assert 'frames_received=0 ' in log.read_text()
                else:
                    assert 'frames_received=1 ' in log.read_text()
                row['passed'] = True
            except Exception as error:
                row['error'] = str(error)
            finally:
                stop.set()
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                    row.update(forced_cleanup=True, passed=False)
                thread.join(timeout=6)
                if thread.is_alive():
                    row.update(peer_thread_timeout=True, passed=False)
                if failures:
                    row.update(peer_errors=failures, passed=False)
        row['detector_log_clean'] = clean(log.read_text())
        row['passed'] &= row['detector_log_clean']
        row['log_sha256'] = sha(log)
        rows.append(row)

    report = dict(scope='real standalone TCP diagnostic executable; no GameEnv simulation',
                  passed=all(row['passed'] for row in rows), cases=rows,
                  binaries={str(path): sha(path) for path in (args.client, args.server)},
                  sources={str(path): sha(path) for path in (
                      Path('engine/src/frame_sync/asio_client.cpp'),
                      Path('engine/src/frame_sync/tcp_client_transport.hpp'),
                      Path('engine/src/frame_sync/tcp_frame_server.hpp'),
                      Path('engine/src/frame_sync/bounded_tcp_writer.hpp'),
                      Path(__file__).resolve(), Path(__file__).with_name('tcp_capacity_probe.py').resolve())})
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
