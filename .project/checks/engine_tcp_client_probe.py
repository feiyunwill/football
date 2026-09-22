#!/usr/bin/env python3
"""Actual GameEnv TCP client: explicit resume and the automatic retry wrapper.

The fixture provisions the first session's existing legacy token. It does not
test secure token issuance, WAN conditions or network prediction latency.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build, output = args.build.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    binary, core = build / 'bin/engine_tcp_client_contract', build / 'libfootball_engine.so'
    env = os.environ.copy()
    for key in ('DISPLAY', 'GFOOTBALL_DATA_DIR', 'GFOOTBALL_FONT', 'LD_PRELOAD', 'SDL_VIDEODRIVER'):
        env.pop(key, None)
    env.update(LD_LIBRARY_PATH=str(build), LIBGL_ALWAYS_SOFTWARE='1',
               ASAN_OPTIONS='halt_on_error=1:detect_leaks=1:quarantine_size_mb=16',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1', LSAN_OPTIONS='exitcode=23')
    cases = []
    for name, flags in (('explicit_resume', []), ('automatic_resume', ['--automatic'])):
        log = output / (name + '.log')
        row = dict(case=name, passed=False)
        try:
            with log.open('w') as stream:
                result = subprocess.run([str(binary), *flags], cwd=ROOT, env=env, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=90)
            text = log.read_text()
            summary = json.loads([line for line in text.splitlines() if line.startswith('{')][-1])
            row.update(exit_code=result.returncode, contract=summary,
                       detector_log_clean=not any(marker in text for marker in (
                           'ERROR: AddressSanitizer', 'ERROR: LeakSanitizer', 'runtime error:',
                           'AddressSanitizer:DEADLYSIGNAL')))
            row['passed'] = (result.returncode == 0 and summary['passed'] and summary['skipped'] == 0
                             and summary['initial_confirmed'] == 12 and summary['resume_frame'] >= 12
                             and summary['final_confirmed'] >= summary['resume_frame'] + 25
                             and summary['resumed_verified_hashes'] >= 2 and summary['actual_nonzero_inputs'] > 0
                             and summary['automatic_reconnect'] == bool(flags) and row['detector_log_clean'])
            if flags:
                row['passed'] &= summary['reconnect_attempts'] == 1
        except Exception as error:
            row['error'] = str(error)
        row['log_sha256'] = sha(log)
        cases.append(row)
    sources = ['engine/tests/engine_tcp_client_contract.cpp', 'engine/src/frame_sync/reconnecting_client.hpp',
               'engine/src/frame_sync/tcp_frame_client.hpp', 'engine/src/frame_sync/tcp_client_transport.hpp',
               'engine/src/frame_sync/engine_tcp_server.hpp', 'engine/src/frame_sync/engine_tcp_bridge.hpp',
               'engine/src/frame_sync/frame_simulation.hpp', 'engine/src/frame_sync/bounded_tcp_writer.hpp',
               '.project/checks/engine_tcp_client_probe.py']
    report = dict(passed=all(row['passed'] for row in cases), cases=cases, scope=__doc__,
                  binary_sha256=sha(binary), engine_sha256=sha(core), build=str(build),
                  sources={path: sha(ROOT / path) for path in sources})
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
