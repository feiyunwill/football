#!/usr/bin/env python3
"""Package a fresh-manual long-match reference from the archived ECS v11 engine."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '.project/checks'))
import match_benchmark as benchmark  # noqa: E402
import soak_analysis  # noqa: E402


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_run(path, seed):
    raw = path.read_bytes()
    lines = [line for line in raw.splitlines() if line.startswith(b'{')]
    if len(lines) != 1:
        raise RuntimeError(f'Expected one long-match result in {path}')
    run = json.loads(lines[0])
    benchmark.validate_run(run, seed, 1000, 36000, run['cpu'])
    if run.get('passed') is not True or run.get('measurement_storage_prefaulted') is not True:
        raise RuntimeError(f'Invalid long-match result in {path}')
    return run, raw


def archive(files):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as tar:
            for name, raw in sorted(files.items()):
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                info.mode = 0o644
                info.mtime = 0
                tar.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-dir', type=Path, required=True)
    parser.add_argument('--candidate-42', type=Path, required=True)
    parser.add_argument('--candidate-43', type=Path, required=True)
    args = parser.parse_args()
    base = args.baseline_dir.resolve()
    ecs_path = ROOT / '.project/optimization/baselines/ecs_v11.json'
    old_path = ROOT / '.project/optimization/baselines/soak_v2.json'
    ecs = json.loads(ecs_path.read_text())
    old = json.loads(old_path.read_text())
    parent_path = ROOT / '.project/optimization/baselines/soak_v8.json'
    parent_sha256 = benchmark.file_hash(parent_path)
    engine = ecs['binaries']['engine']
    executable = old['binaries']['benchmark']
    for entry, binary in ((engine, base / 'libfootball_engine.so'),
                          (executable, base / 'engine_soak_benchmark')):
        packed = (ROOT / entry['path']).read_bytes()
        if sha(packed) != entry['compressed_sha256'] or sha(gzip.decompress(packed)) != entry['sha256']:
            raise RuntimeError(f'Archived binary changed: {entry["path"]}')
        if sha(binary.read_bytes()) != entry['sha256']:
            raise RuntimeError(f'Probe used a different binary: {binary}')
    linkage = subprocess.run(['ldd', str(base / 'engine_soak_benchmark')],
                             env=dict(os.environ, LD_LIBRARY_PATH=str(base)),
                             capture_output=True, text=True, check=True).stdout
    if str(base / 'libfootball_engine.so') not in linkage:
        raise RuntimeError('Probe benchmark does not load the archived ECS v11 engine')

    logs = {}
    runs = []
    validation = {}
    for seed, candidate_path in ((42, args.candidate_42), (43, args.candidate_43)):
        baseline_path = base / f'seed-{seed}.log'
        baseline, baseline_raw = read_run(baseline_path, seed)
        candidate, candidate_raw = read_run(candidate_path.resolve(), seed)
        if not soak_analysis.assess(baseline, seed, baseline['cpu'])['passed']:
            raise RuntimeError(f'Archived-engine baseline fails its budget: seed {seed}')
        result = soak_analysis.assess(candidate, seed, candidate['cpu'], reference=baseline)
        if not result['passed']:
            raise RuntimeError(f'Current engine fails the long-match budget: seed {seed}: {result["failures"]}')
        logs[f'baseline-seed-{seed}.json'] = baseline_raw
        logs[f'candidate-seed-{seed}.json'] = candidate_raw
        validation[str(seed)] = {'baseline_log_sha256': sha(baseline_raw),
                                 'candidate_log_sha256': sha(candidate_raw),
                                 'assertions': result['assertions'],
                                 'trajectory_fields': list(soak_analysis.TRAJECTORY_FIELDS)}
        runs.append(baseline)

    manifest_path = ROOT / '.project/optimization/baselines/soak_v9.json'
    artifact_path = ROOT / '.project/optimization/baselines/soak_v9_reference.json.gz'
    validation_path = ROOT / '.project/optimization/evidence/soak_v9_validation_20261005.tar.gz'
    if any(path.exists() for path in (manifest_path, artifact_path, validation_path)):
        raise RuntimeError('Versioned long-match reference already exists')
    contract = old['measurement_contract']
    identity = 'soak-manual-fresh-pre-ecs-query-20261005'
    artifact = {'format': 9, 'id': identity, 'source_commit': ecs['source_commit'],
                'source_identity': ecs['source_identity'],
                'semantic_patch': ecs['semantic_patch'],
                'measurement_contract': contract,
                'binaries': {'engine': engine['sha256'], 'benchmark': executable['sha256']},
                'command': 'LD_LIBRARY_PATH=ARCHIVED_ENGINE_DIR engine_soak_benchmark SEED CPU',
                'validation': validation, 'runs': runs}
    artifact_raw = (json.dumps(artifact, indent=2) + '\n').encode()
    artifact_packed = gzip.compress(artifact_raw, compresslevel=9, mtime=0)
    validation_packed = archive({**logs, 'linkage.txt': linkage.encode()})
    manifest = {'format': 9, 'id': identity, 'source_commit': ecs['source_commit'],
                'source_identity': ecs['source_identity'],
                'semantic_patch': ecs['semantic_patch'],
                'semantic_patch_sha256': ecs['semantic_patch_sha256'],
                'ecs_reference_sha256': benchmark.file_hash(ecs_path),
                'derived_from_soak_v8_sha256': parent_sha256,
                'derived_from_reference_sha256': old['derived_from_reference_sha256'],
                'measurement_contract': contract,
                'reference_artifact': artifact_path.relative_to(ROOT).as_posix(),
                'artifact_sha256': sha(artifact_packed),
                'artifact_uncompressed_sha256': sha(artifact_raw),
                'validation_artifact': validation_path.relative_to(ROOT).as_posix(),
                'validation_artifact_sha256': sha(validation_packed),
                'generator_sha256': benchmark.file_hash(Path(__file__)),
                'binaries': {'engine': engine, 'benchmark': executable}}
    artifact_path.write_bytes(artifact_packed)
    validation_path.write_bytes(validation_packed)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'passed': True, 'manifest': str(manifest_path),
                      'manifest_sha256': benchmark.file_hash(manifest_path),
                      'validation_sha256': sha(validation_packed), 'seeds': [42, 43]}))


if __name__ == '__main__':
    main()
