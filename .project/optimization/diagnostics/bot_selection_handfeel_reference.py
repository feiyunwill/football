#!/usr/bin/env python3
"""Regenerate the pinned current-handfeel bot-selection oracle from a built engine."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / '.project/optimization/baselines'
FIXTURES = ROOT / 'engine/tests/fixtures'
NAME = 'bot_selection_handfeel_20261002'
HISTORICAL_SHA = '11c2db820ad36644c1c5d5827778ef4ed0b3907c952d168e330cca54852e0699'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def packed(entries: dict[str, bytes]) -> bytes:
    members = {'manifest.json': json.dumps({
        'format': 'bot-selection-handfeel-oracle-v1',
        'files': {name: digest(data) for name, data in sorted(entries.items())},
    }, sort_keys=True, indent=2).encode() + b'\n', **entries}
    stream = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for name, data in sorted(members.items()):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def input_tuple(line: str) -> tuple[float, float, int]:
    fields = line.strip().rstrip(',').strip('{}').split(',')
    return (float.fromhex(fields[0].removesuffix('f')),
            float.fromhex(fields[1].removesuffix('f')), int(fields[2]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path,
                        default=Path('/tmp/football-optimization-native'))
    args = parser.parse_args()
    exe = (args.build / 'bin/engine_native_bot_selection_contract').resolve()
    source = ROOT / 'engine/tests/engine_native_bot_selection_contract.cpp'
    old = subprocess.check_output(
        ['git', 'show', 'a7d49b8:engine/src/onthepitch/player/humanoid/humanoid.cpp'],
        cwd=ROOT)
    assert digest(old) == HISTORICAL_SHA
    snapshot = gzip.compress(old, mtime=0)
    snapshot_path = BASE / f'{NAME}_historical_humanoid.cpp.gz'
    snapshot_path.write_bytes(snapshot)
    old_controller = subprocess.check_output(
        ['git', 'show', 'a7d49b8:engine/src/onthepitch/player/controller/playercontroller.cpp'],
        cwd=ROOT)
    controller_sha = '931c36452a428c67e8f2e37adcb094b156924f05e20c6bd6f2b1dc514f9863c9'
    assert digest(old_controller) == controller_sha
    controller_snapshot = gzip.compress(old_controller, mtime=0)
    controller_snapshot_path = BASE / f'{NAME}_historical_playercontroller.cpp.gz'
    controller_snapshot_path.write_bytes(controller_snapshot)

    members = {'generator.cpp': source.read_bytes()}
    with tempfile.TemporaryDirectory(prefix='football-bot-handfeel-oracle-') as directory:
        temporary = Path(directory)
        for run in (1, 2):
            hashes = temporary / f'hashes-run{run}.inc'
            tail = temporary / f'tail-run{run}.inc'
            result = subprocess.run([str(exe), '--emit-reference', str(hashes), str(tail)],
                                    cwd=ROOT, capture_output=True, timeout=60)
            members[f'run{run}.log'] = (f'exit={result.returncode}\n'.encode() +
                                        result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(members[f'run{run}.log'].decode(errors='replace'))
            members[f'hashes-run{run}.inc'] = hashes.read_bytes()
            members[f'tail-run{run}.inc'] = tail.read_bytes()
    for kind, frames in (('hashes', 512), ('tail', 245)):
        first = members[f'{kind}-run1.inc']
        assert first == members[f'{kind}-run2.inc']
        assert len(first.splitlines()) == frames
        fixture = FIXTURES / f'native_bot_transition_{kind}_handfeel_20261002.inc'
        fixture.write_bytes(b'// Current handfeel replay oracle, generated twice on 2026-10-02.\n' + first)

    previous = (FIXTURES / 'native_bot_transition_hashes_assist_20261001.inc').read_text().splitlines()[1:]
    current = members['hashes-run1.inc'].decode().splitlines()
    changed = [i for i, (a, b) in enumerate(zip(previous, current)) if a != b]
    assert len(previous) == len(current) == 512 and changed
    previous_tail = (FIXTURES / 'native_bot_transition_tail_assist_20261001.inc').read_text().splitlines()[1:]
    current_tail = members['tail-run1.inc'].decode().splitlines()
    assert len(previous_tail) == len(current_tail) == 245
    assert all(input_tuple(a) == input_tuple(b) for a, b in zip(previous_tail, current_tail))
    selected = [int(line.strip().rstrip(',').strip('{}').split(',')[3]) for line in current_tail]
    unavailable = [i for i, actor in enumerate(selected) if actor == -1]
    assert unavailable and any(actor >= 0 for actor in selected[unavailable[-1] + 1:])
    report = json.loads(members['run1.log'].decode().split('\n', 1)[1])
    assert report == json.loads(members['run2.log'].decode().split('\n', 1)[1])
    assert report['unavailable_frames'] == len(unavailable)

    archive_path = BASE / f'{NAME}.tar.gz'
    archive_path.write_bytes(packed(members))
    relative = lambda path: path.relative_to(ROOT).as_posix()
    manifest = {
        'format': 1,
        'id': 'bot-selection-current-handfeel-20261002',
        'historical_reference': '.project/optimization/baselines/bot_selection_assist_20261001.json',
        'candidate_sources': {
            name: digest((ROOT / name).read_bytes())
            for name in ('engine/src/onthepitch/player/controller/playercontroller.cpp',
                         'engine/src/onthepitch/player/humanoid/humanoid.cpp')},
        'historical_source_snapshot': {
            'path': relative(snapshot_path), 'sha256': digest(snapshot),
            'decompressed_sha256': digest(old)},
        'historical_controller_snapshot': {
            'path': relative(controller_snapshot_path),
            'sha256': digest(controller_snapshot),
            'decompressed_sha256': digest(old_controller)},
        'archive': {'path': relative(archive_path), 'sha256': digest(archive_path.read_bytes()),
                    'generator_sha256': digest(members['generator.cpp'])},
        'raw_oracles': {
            'independent_runs': 2,
            'hashes_sha256': digest(members['hashes-run1.inc']),
            'tail_sha256': digest(members['tail-run1.inc'])},
        'fixtures': {
            relative(FIXTURES / f'native_bot_transition_{kind}_handfeel_20261002.inc'):
            digest((FIXTURES / f'native_bot_transition_{kind}_handfeel_20261002.inc').read_bytes())
            for kind in ('hashes', 'tail')},
        'contract': {
            'prefix_frames': 512, 'tail_frames': 245,
            'first_changed_frame_vs_prior': changed[0],
            'changed_prefix_hashes_vs_prior': len(changed),
            'first_unavailable_tail_frame': unavailable[0],
            'unavailable_frames': report['unavailable_frames'],
            'recovered_frames': report['recovered_frames'],
            'opponent_restart_wait_frames': report['opponent_restart_wait_frames'],
        },
    }
    path = BASE / f'{NAME}.json'
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    print(path, digest(path.read_bytes()))
    print(json.dumps(manifest['contract'], sort_keys=True))


if __name__ == '__main__':
    main()
