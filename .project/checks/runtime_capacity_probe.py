#!/usr/bin/env python3
"""Actual native queue/render/log contracts; retain every exit status and raw log."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def no_core_dump():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    build, output = args.build.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    for key in ('DISPLAY', 'GFOOTBALL_DATA_DIR', 'GFOOTBALL_FONT', 'LD_PRELOAD', 'SDL_VIDEODRIVER'):
        env.pop(key, None)
    env.update(LD_LIBRARY_PATH=str(build), LIBGL_ALWAYS_SOFTWARE='1',
               ASAN_OPTIONS='halt_on_error=1:detect_leaks=1:quarantine_size_mb=16',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1', LSAN_OPTIONS='exitcode=23')
    binary = build / 'bin/engine_runtime_contract'
    cases = []
    for name, flags in [('queues', []), ('render', ['--render']), ('logs', ['--logs']), ('fatal', ['--fatal'])]:
        log = output / (name + '.log')
        row = dict(case=name, passed=False)
        try:
            with log.open('w') as stream:
                result = subprocess.run([str(binary), *flags], cwd=ROOT, env=env,
                                        stdout=stream, stderr=subprocess.STDOUT, timeout=180,
                                        preexec_fn=no_core_dump)
            text = log.read_text()
            row['exit_code'] = result.returncode
            clean = not any(marker in text for marker in ('ERROR: AddressSanitizer', 'runtime error:',
                                                          'ERROR: LeakSanitizer', 'AddressSanitizer:DEADLYSIGNAL'))
            row['sanitizers_clean'] = clean
            if name in ('queues', 'render'):
                summary = json.loads([line for line in text.splitlines() if line.startswith('{')][-1])
                row['contract'] = summary
                row['passed'] = result.returncode == 0 and summary['passed'] and summary['skipped'] == 0 and clean
                if name == 'render':
                    row['passed'] &= bool(summary['renderer'])
            elif name == 'logs':
                records = text.splitlines(keepends=True)
                matches = re.findall(r'\[runtime_contract::concurrent\]: worker=(\d+) record=(\d+)\n', text)
                actual = {(int(worker), int(number)) for worker, number in matches}
                expected = {(worker, number) for worker in range(8) for number in range(64)}
                row.update(records=len(records), max_record_bytes=max(map(lambda line: len(line.encode()), records)),
                           unique_concurrent_records=len(actual), truncated_records=text.count('...[truncated]'))
                row['passed'] = (result.returncode == 0 and clean and len(records) == 514 and
                                 len(matches) == 512 and actual == expected and
                                 all(len(line.encode()) <= 4096 for line in records) and
                                 row['truncated_records'] == 1 and 'one two three\n' in text)
            else:
                row['passed'] = (result.returncode == -signal.SIGABRT and clean and
                                 'intentional fatal termination' in text)
                row['limitation'] = 'Fatal abort intentionally bypasses normal destructors; no fatal-path leak claim'
        except Exception as error:
            row['error'] = str(error)
        row['log_sha256'] = sha(log)
        cases.append(row)
        print(json.dumps(row), flush=True)
    sources = ['engine/src/types/messagequeue.hpp', 'engine/src/systems/graphics/graphics_task.cpp',
               'engine/src/game_env.cpp', 'engine/src/base/log.cpp', 'engine/src/base/log.hpp',
               'engine/tests/engine_runtime_contract.cpp', '.project/checks/runtime_capacity_probe.py']
    report = dict(passed=all(row['passed'] for row in cases), cases=cases,
                  sources={path: sha(ROOT / path) for path in sources},
                  binaries={'contract': sha(binary), 'engine': sha(build / 'libfootball_engine.so')},
                  scope='Fixed object storage and actual texture references; not full GPU or process RSS budget')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
