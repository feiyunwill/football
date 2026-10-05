#!/usr/bin/env python3
"""Audit current milestone evidence, shipped artifacts, and known severe issues."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / '.project/optimization/benchmarks'
ISSUES = ROOT / '.project/optimization/known_issues.json'
DOMAINS = tuple(f'ms-{number}.1' for number in range(19, 26))
PRODUCT_TASKS = ('task-26.1.1.1', 'task-26.1.1.2', 'task-26.1.2.1')
SEVERE = {'blocker', 'critical', 'high'}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_artifact_children(path: Path, check) -> dict[str, str]:
    """Verify the command logs and package files cited by an acceptance report."""
    report = json.loads(path.read_text())
    base = path.parent.resolve()
    verified: dict[str, str] = {}

    def verify(candidate: str | Path | None, expected: str | None,
               description: str) -> None:
        valid_hash = isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected)
        valid_path = isinstance(candidate, (str, Path)) and bool(str(candidate))
        if not valid_hash or not valid_path:
            check(False, f'{description} lacks a path or SHA-256')
            return
        child = Path(candidate)
        if not child.is_absolute():
            child = base / child
        child = child.resolve()
        in_artifact = child.is_relative_to(base)
        matches = in_artifact and child.is_file() and sha(child) == expected
        check(matches, f'{description} is absent, outside its artifact, or differs from SHA-256')
        if matches:
            verified[str(child.relative_to(base))] = expected

    commands = report.get('commands', [])
    check(isinstance(commands, list), f'{path} has invalid command records')
    for command in commands if isinstance(commands, list) else []:
        if not isinstance(command, dict):
            check(False, f'{path} contains an invalid command record')
            continue
        log = command.get('log')
        if log is None and isinstance(command.get('label'), str):
            log = command['label'] + '.log'
        verify(log, command.get('log_sha256') or command.get('sha256'),
               f'{path} command log')

    runs = report.get('runs', [])
    check(isinstance(runs, list), f'{path} has invalid run records')
    for run in runs if isinstance(runs, list) else []:
        if not isinstance(run, dict):
            check(False, f'{path} contains an invalid run record')
            continue
        if 'log_sha256' not in run:
            continue
        log = run.get('log')
        if log is None and isinstance(run.get('build'), str) and isinstance(run.get('seed'), int):
            log = f"{run['build']}-{run['seed']}.log"
        verify(log, run['log_sha256'], f'{path} measured run log')

    if 'wheel' in report:
        wheel = report['wheel']
        check(isinstance(wheel, dict), f'{path} has invalid wheel identity')
        if isinstance(wheel, dict):
            verify(wheel.get('path'), wheel.get('sha256'), f'{path} wheel')
            check(wheel.get('sha256') == report.get('build', {}).get('wheel_sha256'),
                  f'{path} build and wheel hashes differ')
    if 'probe_report_sha256' in report:
        verify('installed-probe/report.json', report['probe_report_sha256'],
               f'{path} package probe report')
    return verified


def main() -> int:
    output = BENCHMARKS / f'product-release-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    report: dict = {'passed': False, 'assertions': 0, 'skipped': 0,
                    'failures': [], 'artifact': str(output / 'report.json')}

    def check(condition: bool, message: str) -> None:
        report['assertions'] += 1
        if not condition:
            report['failures'].append(message)

    try:
        check(platform.system() == 'Linux' and platform.machine() == 'x86_64' and
              sys.flags.optimize == 0, 'Release audit needs Linux x86_64 and assertions')
        sys.path.insert(0, str(ROOT / '.project'))
        from quality import Program
        program = Program(ROOT)
        states = program.states()
        report['milestones'] = {name: states[name] for name in DOMAINS}
        report['product_tasks'] = {name: states[name] for name in PRODUCT_TASKS}
        for name in DOMAINS + PRODUCT_TASKS:
            check(states[name] == 'verified', f'{name} is {states[name]}')

        records = {}
        artifacts = {}
        artifact_children = {}
        for name, definition in program.checks.items():
            if name == 'product_release' or not definition['ready']:
                continue
            state = program.check_state(name)
            check(state == 'verified', f'{name} evidence is {state}')
            if state != 'verified':
                continue
            evidence_path = program.evidence_dir / f'{name}.json'
            record = json.loads(evidence_path.read_text())
            log = program.evidence_dir / record['log']
            records[name] = {'fingerprint': record['fingerprint'],
                             'evidence_sha256': sha(evidence_path),
                             'log_sha256': sha(log)}
            if definition['kind'] != 'json':
                continue
            summary = json.loads(log.read_text().strip().splitlines()[-1])
            artifact_name = summary.get('artifact')
            artifact_sha = summary.get('artifact_sha256')
            if artifact_name is None and artifact_sha is None:
                continue
            check(isinstance(artifact_name, str) and isinstance(artifact_sha, str),
                  f'{name} provided incomplete artifact identity')
            if not isinstance(artifact_name, str) or not isinstance(artifact_sha, str):
                continue
            path = Path(artifact_name)
            if not path.is_absolute():
                path = ROOT / path
            check(path.is_file() and sha(path) == artifact_sha,
                  f'{name} artifact is absent or differs from its recorded hash')
            if path.is_file():
                artifacts[name] = {'path': str(path), 'sha256': sha(path)}
                artifact_children[name] = audit_artifact_children(path, check)
        report['checks'] = records
        report['artifacts'] = artifacts
        report['artifact_children'] = artifact_children

        issues = json.loads(ISSUES.read_text())
        check(issues.get('schema') == 'football-known-issues-v1' and
              isinstance(issues.get('issues'), list), 'Known-issues ledger is invalid')
        blocking = []
        for issue in issues.get('issues', []):
            check(isinstance(issue.get('id'), str) and
                  issue.get('severity') in SEVERE | {'medium', 'low'} and
                  issue.get('status') in {'open', 'closed'},
                  'Known issue has invalid identity, severity, or state')
            evidence = ROOT / issue.get('evidence', '')
            check(evidence.is_file() and evidence.resolve().is_relative_to(ROOT),
                  f"Known issue {issue.get('id')} lacks local evidence")
            if issue.get('severity') in SEVERE and issue.get('status') == 'open':
                blocking.append(issue.get('id'))
            if issue.get('status') == 'closed':
                closure = ROOT / (issue.get('closure_evidence') or '')
                check(closure.is_file() and closure.resolve().is_relative_to(ROOT),
                      f"Closed issue {issue.get('id')} lacks closure evidence")
        check(not blocking, 'Open severe issues: ' + ', '.join(blocking))
        report['open_severe_issues'] = blocking

        changed = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD', '--', 'engine', 'gfootball',
             '.project/checks', '.project/optimization/program.json',
             '.project/optimization/known_issues.json', 'setup.py', 'pyproject.toml'],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
        untracked = subprocess.run(
            ['git', 'ls-files', '--others', '--exclude-standard', '--',
             'engine', 'gfootball', '.project/checks'],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
        check(not changed and not untracked,
              'Release source is not committed: ' + ', '.join(changed + untracked))
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout.strip()
        report['source_commit'] = commit
        report['platform'] = platform.platform()
        check(report['assertions'] >= 30, 'Release audit exercised too few assertions')
        report['passed'] = not report['failures']
    except BaseException as error:
        report['failures'].append(str(error))
    finally:
        artifact = output / 'report.json'
        artifact.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'],
                          'assertions': report['assertions'],
                          'skipped': report['skipped'],
                          'failures': report['failures'],
                          'artifact': str(artifact),
                          'artifact_sha256': sha(artifact)}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
