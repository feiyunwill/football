"""Assemble the audited schema8 seed-42 recovery with the four-seed study.

This is a narrow, non-training bridge.  It preserves the failed full-study
receipt, rechecks every imported artifact, and evaluates only the recovered
seed on the already frozen prospective cases.  Candidate confirmation remains
closed; a separate auditor and fresh confirmation are required afterwards.
"""
import argparse
import json
import math
import os
import subprocess
from pathlib import Path

import quality
from validate import ROOT, sha, source_fingerprint

SEEDS = (42, 123, 2026, 31415, 271828)
REMAINING_SEEDS = SEEDS[1:]
TARGETS = (1024, 2048, 3072, 4096, 5120, 6144, 7168, 7424, 7680, 7936, 8192)


def read(path):
  return json.loads(path.read_text())


def write(path, value):
  path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def lines(path):
  return [json.loads(line) for line in path.read_text().splitlines()]


def validation_cell(seed, rows):
  return dict(seed=seed,
      goals=sum(row['controlled_score_delta'] > 0 for row in rows),
      passes=sum(row['completed_passes'] > 0 for row in rows),
      joint=sum(row['completed_passes'] > 0 and row['controlled_score_delta'] > 0 for row in rows),
      groups=[sum(row['controlled_score_delta'] > 0 for row in rows if row['group'] == group)
              for group in range(5)])


def checked_rows(path, ids):
  data = lines(path)
  summary = data.pop()
  assert summary['complete'] and len(data) == 200
  assert [(row['index'], row['group'], row['engine_seed']) for row in data] == ids
  for row in data:
    assert row['terminated'] ^ row['truncated']
    assert 0 <= row['completed_passes'] <= row['pass_requests'] <= row['steps'] <= 256
    assert all(math.isfinite(row[key]) for key in ('reward', 'controlled_score_delta'))
  return data


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  for name in ('recovery', 'recovery_audit', 'remaining', 'quality', 'build', 'output'):
    parser.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
  args = parser.parse_args()
  recovery_root = args.recovery.resolve()
  recovery_audit_root = args.recovery_audit.resolve()
  remaining_root = args.remaining.resolve()
  quality_root = args.quality.resolve()
  build = args.build.resolve()
  out = args.output.resolve()
  assert out != ROOT and ROOT not in out.parents
  out.mkdir(parents=True, exist_ok=False)
  report = dict(passed=False, validation_passed=False, candidate_accepted=False)
  try:
    before = source_fingerprint()
    recovery = read(recovery_root / 'report.json')
    recovery_protocol = read(recovery_root / 'protocol.json')
    recovery_audit = read(recovery_audit_root / 'report.json')
    remaining = read(remaining_root / 'report.json')
    remaining_protocol = read(remaining_root / 'protocol.json')
    quality_receipt = quality.verify(quality_root / 'report.json')

    assert recovery['passed'] and not recovery['candidate_accepted']
    assert recovery['seed'] == recovery_protocol['seed'] == 42
    assert recovery_protocol['payload_schema'] == 8 and recovery_protocol['targets'] == list(TARGETS)
    assert recovery['source_sha256'] == recovery_protocol['source']['sha256'] == before['sha256']
    assert recovery_audit['passed'] and not recovery_audit['candidate_accepted']
    assert recovery_audit['report_sha256'] == sha(recovery_root / 'report.json')
    assert recovery_audit['protocol_sha256'] == sha(recovery_root / 'protocol.json')
    assert all(sha(Path(path)) == digest for path, digest in recovery_protocol['frozen'].items())

    original = Path(recovery_protocol['original_study'])
    original_report = read(original / 'report.json')
    assert not original_report['passed']
    assert original_report['error'] == "AssertionError: ('starts-midl_mean4-42', None)"
    assert sha(original / 'report.json') == recovery_protocol['original_report_sha256']
    assert recovery['training_seconds'] == original_report['training_seconds'] < 2520
    assert len(recovery['chunks']) == len(TARGETS)
    assert [chunk['version'] for chunk in recovery['chunks']] == list(TARGETS)
    assert all(sha(Path(chunk['checkpoint'])) == chunk['checkpoint_sha256'] for chunk in recovery['chunks'])
    assert sha(Path(recovery['raw_checkpoint'])) == recovery['raw_checkpoint_sha256']
    assert sha(Path(recovery['policy'])) == recovery['policy_sha256']
    assert sha(Path(recovery['provenance_manifest'])) == recovery['provenance_sha256']

    assert remaining['passed'] and remaining['source_before'] == remaining['source_after'] == remaining_protocol['source'] == before
    assert remaining_protocol['remaining_seeds_only'] and tuple(remaining_protocol['seeds']) == REMAINING_SEEDS
    assert remaining_protocol['payload_schema'] == 8 and remaining_protocol['checkpoint_targets'] == list(TARGETS)
    assert remaining_protocol['validation_gates'] == dict(total=970, seed=180, group=180, passes=40, joint=40)
    old_study = Path(remaining_protocol['old_study']).resolve()
    mean_study = Path(remaining_protocol['mean_study']).resolve()
    assert (old_study / 'report.json').is_file() and (mean_study / 'report.json').is_file()
    assert sha(remaining_root / 'protocol.json') == remaining['protocol_sha256']
    assert all(sha(Path(path)) == digest for path, digest in remaining_protocol['frozen'].items())
    assert len(remaining['commands']) == 62 and all(row['exit_code'] == 0 for row in remaining['commands'])
    for command in remaining['commands']:
      assert sha(remaining_root / (command['name'] + '.log')) == command['stdout_sha256']
      assert sha(remaining_root / (command['name'] + '.stderr')) == command['stderr_sha256']
    assert [model['seed'] for model in remaining['models']] == list(REMAINING_SEEDS)
    assert all(model['configuration'] == 'midl_mean4' and model['final_version'] == 8192
               and len(model['chunks']) == len(TARGETS) for model in remaining['models'])

    cases = remaining_root / 'cases.txt'
    case_lines = cases.read_text().splitlines()
    assert len(case_lines) == 200
    ids = [tuple(map(int, line.split()[:2] + [line.split()[3]])) for line in case_lines]
    assert len({entry[2] for entry in ids}) == 200
    assert [sum(entry[1] == group for entry in ids) for group in range(5)] == [40] * 5

    here = Path(__file__).parent
    auditor = here / 'audit_o23_midl_recovery_study.py'
    files = [Path(__file__), auditor, recovery_root / 'report.json', recovery_root / 'protocol.json',
             recovery_audit_root / 'report.json', remaining_root / 'report.json',
             remaining_root / 'protocol.json', quality_root / 'report.json', cases,
             build / 'bin/native_ppo_train', build / 'libfootball_engine.so',
             Path(recovery['policy']), Path(recovery['provenance_manifest']),
             old_study / 'report.json', mean_study / 'report.json']
    files.extend(Path(model['policy']) for model in remaining['models'])
    frozen = {str(path.resolve()): sha(path) for path in files}
    protocol = dict(schema='o23_schema8_recovery_assembly_v1', source=before,
        quality=str((quality_root / 'report.json').resolve()), build=str(build),
        recovery=str(recovery_root), recovery_audit=str(recovery_audit_root), remaining=str(remaining_root),
        old_study=str(old_study), mean_study=str(mean_study),
        frozen=frozen, payload_schema=8, seeds=list(SEEDS), remaining_seeds=list(REMAINING_SEEDS),
        checkpoint_targets=list(TARGETS), validation_cases=str(cases.resolve()),
        validation_cases_sha256=sha(cases), validation_gates=dict(total=970, seed=180, group=180, passes=40, joint=40),
        candidate_accepted=False,
        scope='Assemble completed seed42 recovery plus frozen remaining-seed study; one seed42 prospective evaluation only. Fresh confirmation remains unopened.')
    write(out / 'protocol.json', protocol)

    def unchanged():
      assert source_fingerprint() == before
      assert all(sha(Path(path)) == digest for path, digest in frozen.items())

    env = dict(os.environ, LD_LIBRARY_PATH=str(build), GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
        GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    name = 'validation-midl_mean4-42'
    with (out / (name + '.log')).open('w') as stream, (out / (name + '.stderr')).open('w') as errors:
      result = subprocess.run([str(build / 'bin/native_ppo_train'), '--inference-mode', 'balanced',
          '--policy', recovery['policy'], '--inference-cases', str(cases)], cwd=build, env=env,
          stdout=stream, stderr=errors, timeout=300)
    assert result.returncode == 0
    seed42_rows = checked_rows(out / (name + '.log'), ids)
    validation = [validation_cell(42, seed42_rows)]
    models = [dict(configuration='midl_mean4', seed=42, initial_version=0, final_version=8192,
        path=recovery['raw_checkpoint'], sha256=recovery['raw_checkpoint_sha256'],
        policy=recovery['policy'], policy_sha256=recovery['policy_sha256'],
        policy_kind='within_seed_mean4_v1', provenance_manifest=recovery['provenance_manifest'],
        provenance_sha256=recovery['provenance_sha256'], chunks=recovery['chunks'],
        conservative_episode_starts=recovery['conservative_episode_starts'], starts=recovery['starts'],
        starts_sha256=recovery['starts_sha256'], training_seconds=recovery['training_seconds'],
        recovered_from=str(original))]
    for model in remaining['models']:
      rows = checked_rows(remaining_root / ('validation-midl_mean4-' + str(model['seed']) + '.log'), ids)
      validation.append(validation_cell(model['seed'], rows))
      models.append(dict(model, starts=str((remaining_root / ('starts-midl_mean4-' + str(model['seed']) + '.log')).resolve())))
    validation.sort(key=lambda row: SEEDS.index(row['seed']))
    models.sort(key=lambda row: SEEDS.index(row['seed']))
    total = sum(row['goals'] for row in validation)
    groups = [sum(row['groups'][group] for row in validation) for group in range(5)]
    gates = dict(mean=total >= 970, every_seed=all(row['goals'] >= 180 for row in validation),
        groups=all(value >= 180 for value in groups),
        cooperation=all(row['passes'] >= 40 and row['joint'] >= 40 for row in validation))
    unchanged()
    report.update(passed=True, validation_passed=all(gates.values()), candidate_accepted=False,
        selected='midl_mean4',
        source_before=before, source_after=source_fingerprint(), protocol_sha256=sha(out / 'protocol.json'),
        quality=quality_receipt, models=models, validation=validation, gates=gates,
        candidate_mean=total / 1000, candidate_group_means=[value / 200 for value in groups],
        commands=[dict(name=name, exit_code=result.returncode, stdout_sha256=sha(out / (name + '.log')),
                       stderr_sha256=sha(out / (name + '.stderr')))],
        imported=dict(recovery_report_sha256=sha(recovery_root / 'report.json'),
                      recovery_audit_sha256=sha(recovery_audit_root / 'report.json'),
                      remaining_report_sha256=sha(remaining_root / 'report.json')))
  except BaseException as error:
    report['error'] = f'{type(error).__name__}: {error}'
    report.setdefault('source_after', source_fingerprint())
  write(out / 'report.json', report)
  print(json.dumps({key: report.get(key) for key in ('passed', 'validation_passed', 'candidate_mean', 'error')}), flush=True)
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
