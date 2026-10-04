#!/usr/bin/env python3
"""Freeze the released-pass bot replay as a new oracle, preserving older oracles."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / '.project/optimization/baselines'
SOURCE = ROOT / 'engine/tests/engine_native_bot_selection_contract.cpp'
FIXTURE = ROOT / 'engine/tests/fixtures/native_bot_transition_tail_pass_buffer_20261004.inc'
PARENT = BASE / 'bot_selection_player_switch_20261004.json'
NAME = 'bot_selection_pass_buffer_20261004'
HEADER = b'// Pass-buffer release route: 1531 scripted frames, then live bot and pulsed opponent restart; generated twice on 2026-10-04.\n'
GAMEPLAY_SOURCES = (
    'engine/src/onthepitch/player/controller/humancontroller.cpp',
    'engine/src/onthepitch/player/controller/humancontroller.hpp',
    'engine/src/onthepitch/player/controller/playercontroller.cpp',
)
CONTRACT = {
    'prefix_frames': 512, 'tail_frames': 1735, 'scripted_frames': 1531,
    'historical_input_frames': 245, 'first_unavailable_tail_frame': 1531,
    'unavailable_frames': 105, 'recovered_frames': 98,
    'opponent_restart_wait_frames': 32, 'active_bot_frames': 66,
    'emit_assertions': 4473, 'normal_assertions': 8553,
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fields(line: str) -> list[str]:
    return line.strip().rstrip(',').strip('{}').split(',')


def packed(entries: dict[str, bytes]) -> bytes:
    rows = {'manifest.json': json.dumps({
        'format': 'bot-selection-pass-buffer-oracle-v1',
        'files': {name: digest(data) for name, data in sorted(entries.items())},
    }, sort_keys=True, indent=2).encode() + b'\n', **entries}
    stream = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for name, data in sorted(rows.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def main() -> None:
    build = Path('/tmp/football-optimization-native')
    executable = build / 'bin/engine_native_bot_selection_contract'
    for path in (executable, build / 'libfootball_engine.so', SOURCE, FIXTURE, PARENT):
        if not path.is_file():
            raise RuntimeError(f'Missing oracle input: {path}')
    for path in (BASE / f'{NAME}.json', BASE / f'{NAME}.tar.gz'):
        if path.exists():
            raise RuntimeError(f'Versioned oracle already exists: {path}')
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'engine/src'],
                      cwd=ROOT).returncode:
        raise RuntimeError('Gameplay source differs from pinned commit')
    if json.loads(PARENT.read_text())['id'] != 'bot-selection-player-switch-20261004':
        raise RuntimeError('Wrong historical parent')
    environment = dict(os.environ, LD_LIBRARY_PATH=str(build),
                       GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'))
    environment.pop('LD_PRELOAD', None)
    members = {'generator.cpp': SOURCE.read_bytes()}
    with tempfile.TemporaryDirectory(prefix='football-pass-buffer-oracle-') as directory:
        temporary = Path(directory)
        for run in (1, 2):
            hashes = temporary / f'hashes-run{run}.inc'
            tail = temporary / f'tail-run{run}.inc'
            for label, args in (('emit', ['--emit-reference', str(hashes), str(tail)]),
                                ('normal', [])):
                result = subprocess.run([str(executable), *args], cwd=ROOT,
                                        env=environment, capture_output=True, timeout=120)
                log = f'exit={result.returncode}\n'.encode() + result.stdout + result.stderr
                members[f'{label}-run{run}.log'] = log
                if result.returncode:
                    raise RuntimeError(log.decode(errors='replace'))
            members[f'hashes-run{run}.inc'] = hashes.read_bytes()
            members[f'tail-run{run}.inc'] = tail.read_bytes()
    for kind in ('hashes', 'tail'):
        if members[f'{kind}-run1.inc'] != members[f'{kind}-run2.inc']:
            raise RuntimeError(f'{kind} replays differ')
    for kind in ('emit', 'normal'):
        if members[f'{kind}-run1.log'] != members[f'{kind}-run2.log']:
            raise RuntimeError(f'{kind} reports differ')
    def report(kind: str) -> dict:
        return json.loads(members[f'{kind}-run1.log'].split(b'\n', 1)[1])
    expected = {'passed': True, 'prefix_frames': 512, 'recorded_tail_frames': 1735,
                'unavailable_frames': 105, 'skipped': 0, 'actual_gameenv': True,
                'recovered_frames': 98, 'opponent_restart_wait_frames': 32}
    if report('emit') != dict(expected, assertions=4473) or \
            report('normal') != dict(expected, assertions=8553):
        raise RuntimeError('Bot replay coverage changed')
    hashes = members['hashes-run1.inc'].decode().splitlines()
    prior_hashes = (ROOT / 'engine/tests/fixtures/native_bot_transition_hashes_player_switch_20261004.inc').read_text().splitlines()[1:]
    tail = members['tail-run1.inc'].decode().splitlines()
    prior_tail = (ROOT / 'engine/tests/fixtures/native_bot_transition_tail_player_switch_20261004.inc').read_text().splitlines()[1:]
    legacy = (ROOT / 'engine/tests/fixtures/native_bot_transition_tail_response_20261002.inc').read_text().splitlines()[1:]
    selected = [int(fields(row)[3]) for row in tail]
    if not (len(hashes) == len(prior_hashes) == 512 and hashes == prior_hashes and
            len(tail) == 1735 and len(legacy) == 245 and
            all(fields(a)[:3] == fields(b)[:3] for a, b in zip(legacy, tail[:245])) and
            all(fields(a)[:3] == fields(b)[:3] for a, b in zip(prior_tail[:1531], tail[:1531])) and
            all(actor >= 0 for actor in selected[:1531]) and
            selected[1531:1636] == [-1] * 105 and
            all(actor >= 0 for actor in selected[1636:])):
        raise RuntimeError('Bot replay trajectory or scripted prefix changed')
    if FIXTURE.read_bytes() != HEADER + members['tail-run1.inc']:
        raise RuntimeError('Current fixture differs from independent replay')
    archive = packed(members)
    archive_path = BASE / f'{NAME}.tar.gz'
    archive_path.write_bytes(archive)
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                             text=True).strip()
    manifest = {
        'format': 1, 'id': 'bot-selection-pass-buffer-20261004',
        'historical_reference': PARENT.relative_to(ROOT).as_posix(),
        'historical_reference_sha256': digest(PARENT.read_bytes()),
        'gameplay_source_commit': source_commit,
        'gameplay_sources': {name: digest((ROOT / name).read_bytes()) for name in GAMEPLAY_SOURCES},
        'generator_sha256': digest(Path(__file__).read_bytes()),
        'test_source_sha256': digest(SOURCE.read_bytes()),
        'engine_sha256': digest((build / 'libfootball_engine.so').read_bytes()),
        'binary_sha256': digest(executable.read_bytes()),
        'fixture': {'path': FIXTURE.relative_to(ROOT).as_posix(),
                    'sha256': digest(FIXTURE.read_bytes())},
        'archive': {'path': archive_path.relative_to(ROOT).as_posix(),
                    'sha256': digest(archive)},
        'raw_oracles': {'independent_runs': 2,
                        'hashes_sha256': digest(members['hashes-run1.inc']),
                        'tail_sha256': digest(members['tail-run1.inc'])},
        'contract': CONTRACT,
    }
    (BASE / f'{NAME}.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'manifest': str(BASE / f'{NAME}.json'), 'contract': CONTRACT,
                      'archive_sha256': digest(archive)}, sort_keys=True))


if __name__ == '__main__':
    main()
