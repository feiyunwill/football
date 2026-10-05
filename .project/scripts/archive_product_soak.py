#!/usr/bin/env python3
"""Archive a passing product soak report with its verified raw logs."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / '.project/optimization/evidence'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def archive(report_path: Path, output: Path) -> dict:
    report_path = report_path.resolve(strict=True)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    require(report.get('passed') is True and report.get('skipped') == 0 and
            report.get('assertions', 0) >= 300, 'Soak report did not pass acceptance')
    require(report.get('seeds') == [42, 43, 44] and
            report.get('frames_per_seed') == 36000 and
            report.get('measured_frames_by_build') ==
            {'release': 108000, 'sanitized': 108000},
            'Soak report does not cover the full product workload')

    sys.path.insert(0, str(ROOT / '.project/checks'))
    import product_soak
    sources = product_soak.source_manifest()
    source_hash = digest(json.dumps(sources, sort_keys=True).encode())
    require(source_hash == report.get('source_manifest_sha256'),
            'Current soak sources differ from those accepted')
    tracked = subprocess.run(['git', 'diff', '--name-only', 'HEAD', '--', *sources],
                             cwd=ROOT, capture_output=True, text=True, check=True)
    require(not tracked.stdout.strip(), 'Accepted soak sources are not committed')
    committed = subprocess.run(['git', 'ls-files', '--cached', '--', *sources],
                               cwd=ROOT, capture_output=True, text=True, check=True)
    require(set(committed.stdout.splitlines()) == set(sources),
            'Accepted soak sources contain files absent from the commit')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()

    files: dict[str, bytes] = {'report.json': report_bytes}

    def add_log(name: str, expected: str) -> None:
        require(name.endswith('.log') and Path(name).name == name,
                f'Invalid soak log name: {name}')
        require(isinstance(expected, str) and len(expected) == 64,
                f'Missing SHA-256 for {name}')
        candidate = (report_path.parent / name).resolve()
        require(candidate.is_relative_to(report_path.parent),
                f'Soak log leaves its artifact directory: {name}')
        data = candidate.read_bytes()
        require(digest(data) == expected, f'Soak log differs from report: {name}')
        if name in files:
            require(files[name] == data, f'Conflicting soak log: {name}')
        files[name] = data

    commands = report.get('commands')
    runs = report.get('runs')
    require(isinstance(commands, list) and isinstance(runs, list) and len(runs) == 6,
            'Soak command or run records are incomplete')
    for command in commands:
        add_log(f"{command['label']}.log", command['log_sha256'])
    for run in runs:
        add_log(f"{run['build']}-{run['seed']}.log", run['log_sha256'])
    require({(run['build'], run['seed']) for run in runs} ==
            {(build, seed) for build in ('release', 'sanitized')
             for seed in (42, 43, 44)}, 'Soak build/seed coverage is incomplete')

    binaries = report.get('binaries', {})
    require(set(binaries) == {'release', 'sanitized'},
            'Soak binary provenance is incomplete')
    for build, record in binaries.items():
        for kind, hash_key in (('benchmark', 'benchmark_sha256'),
                               ('engine', 'engine_sha256')):
            require(digest(Path(record[kind]).read_bytes()) == record[hash_key],
                    f'{build} {kind} differs from the measured binary')

    manifest = {'schema': 'football-product-soak-archive-v1',
                'source_commit': commit,
                'source_manifest_sha256': source_hash,
                'binary_hashes': binaries,
                'files': {name: digest(data) for name, data in sorted(files.items())}}
    files['manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, mode='x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zipped:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zipped.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED,
                            compresslevel=9)
    with zipfile.ZipFile(output) as zipped:
        require(sorted(zipped.namelist()) == sorted(files) and
                all(zipped.read(name) == data for name, data in files.items()),
                'Soak archive did not round-trip its verified inputs')
    return verify_archive(output)


def verify_archive(path: Path) -> dict:
    path = path.resolve(strict=True)
    with zipfile.ZipFile(path) as zipped:
        require(zipped.testzip() is None, 'Soak archive has a damaged ZIP member')
        manifest = json.loads(zipped.read('manifest.json'))
        require(manifest.get('schema') == 'football-product-soak-archive-v1' and
                isinstance(manifest.get('files'), dict),
                'Soak archive manifest is invalid')
        hashes = manifest['files']
        require(set(zipped.namelist()) == set(hashes) | {'manifest.json'},
                'Soak archive membership differs from its manifest')
        for name, expected in hashes.items():
            require(digest(zipped.read(name)) == expected,
                    f'Soak archive member differs from its SHA-256: {name}')
        report = json.loads(zipped.read('report.json'))
        require(report.get('passed') is True and report.get('skipped') == 0 and
                report.get('assertions', 0) >= 300 and
                report.get('seeds') == [42, 43, 44] and
                report.get('frames_per_seed') == 36000 and
                report.get('measured_frames_by_build') ==
                {'release': 108000, 'sanitized': 108000},
                'Soak archive does not contain passing product evidence')
        require({(run['build'], run['seed']) for run in report['runs']} ==
                {(build, seed) for build in ('release', 'sanitized')
                 for seed in (42, 43, 44)} and len(report['runs']) == 6,
                'Soak archive is missing measured build/seed coverage')
        require(manifest.get('source_manifest_sha256') ==
                report.get('source_manifest_sha256') and
                manifest.get('binary_hashes') == report.get('binaries'),
                'Soak archive provenance differs from the accepted report')
        for command in report['commands']:
            name = f"{command['label']}.log"
            require(hashes.get(name) == command['log_sha256'],
                    f'Soak command log hash differs from report: {name}')
        for run in report['runs']:
            name = f"{run['build']}-{run['seed']}.log"
            require(hashes.get(name) == run['log_sha256'],
                    f'Soak measured log hash differs from report: {name}')
    return {'archive': str(path), 'sha256': digest(path.read_bytes()),
            'source_commit': manifest['source_commit'],
            'logs': len(hashes) - 1,
            'report_sha256': hashes['report.json']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path, nargs='?')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify is not None:
        require(args.report is None and args.output is None,
                'Archive verification does not accept a report or output')
        print(json.dumps(verify_archive(args.verify)))
        return 0
    require(args.report is not None, 'A passing soak report is required')
    report = args.report.resolve()
    output = args.output or EVIDENCE / ('product_soak_' + digest(report.read_bytes())[:12] + '.zip')
    print(json.dumps(archive(report, output.resolve())))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
