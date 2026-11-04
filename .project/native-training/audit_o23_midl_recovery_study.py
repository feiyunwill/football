"""Independently audit the schema8 seed-42 recovery assembly.

The audit intentionally records, rather than erases, the earlier failed
five-seed attempt.  Passing this audit only opens fresh confirmation; it never
marks the candidate accepted.
"""
import argparse
import json
import math
from pathlib import Path

import quality
from validate import sha, source_fingerprint

SEEDS = (42, 123, 2026, 31415, 271828)
REMAINING_SEEDS = SEEDS[1:]
TARGETS = (1024, 2048, 3072, 4096, 5120, 6144, 7168, 7424, 7680, 7936, 8192)


def read(path):
  return json.loads(path.read_text())


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
  parser.add_argument('--study', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  root = args.study.resolve()
  out = args.output.resolve()
  out.mkdir(parents=True, exist_ok=False)
  result = dict(passed=False, validation_passed=False, candidate_accepted=False)
  try:
    protocol = read(root / 'protocol.json')
    report = read(root / 'report.json')
    assert protocol['schema'] == 'o23_schema8_recovery_assembly_v1'
    assert protocol['seeds'] == list(SEEDS) and protocol['remaining_seeds'] == list(REMAINING_SEEDS)
    assert protocol['payload_schema'] == 8 and protocol['checkpoint_targets'] == list(TARGETS)
    assert protocol['validation_gates'] == dict(total=970, seed=180, group=180, passes=40, joint=40)
    assert not protocol['candidate_accepted'] and report['passed'] and not report['candidate_accepted']
    assert report['selected'] == 'midl_mean4'
    assert report['source_before'] == report['source_after'] == protocol['source'] == source_fingerprint()
    assert report['protocol_sha256'] == sha(root / 'protocol.json')
    assert all(sha(Path(path)) == digest for path, digest in protocol['frozen'].items())
    quality.verify(Path(protocol['quality']))

    recovery_root = Path(protocol['recovery'])
    recovery = read(recovery_root / 'report.json')
    recovery_protocol = read(recovery_root / 'protocol.json')
    recovery_audit = read(Path(protocol['recovery_audit']) / 'report.json')
    assert recovery['passed'] and not recovery['candidate_accepted'] and recovery['seed'] == 42
    assert recovery_protocol['payload_schema'] == 8 and recovery_protocol['targets'] == list(TARGETS)
    assert recovery_audit['passed'] and not recovery_audit['candidate_accepted']
    assert recovery_audit['report_sha256'] == sha(recovery_root / 'report.json')
    assert recovery_audit['protocol_sha256'] == sha(recovery_root / 'protocol.json')
    assert all(sha(Path(path)) == digest for path, digest in recovery_protocol['frozen'].items())
    original = Path(recovery_protocol['original_study'])
    original_report = read(original / 'report.json')
    assert not original_report['passed'] and original_report['error'] == "AssertionError: ('starts-midl_mean4-42', None)"
    assert recovery['training_seconds'] == original_report['training_seconds'] < 2520
    assert [chunk['version'] for chunk in recovery['chunks']] == list(TARGETS)
    assert all(sha(Path(chunk['checkpoint'])) == chunk['checkpoint_sha256'] for chunk in recovery['chunks'])

    remaining_root = Path(protocol['remaining'])
    remaining = read(remaining_root / 'report.json')
    remaining_protocol = read(remaining_root / 'protocol.json')
    assert remaining['passed'] and remaining['source_before'] == remaining['source_after'] == protocol['source']
    assert remaining_protocol['remaining_seeds_only'] and tuple(remaining_protocol['seeds']) == REMAINING_SEEDS
    assert remaining_protocol['payload_schema'] == 8 and remaining_protocol['checkpoint_targets'] == list(TARGETS)
    assert remaining['protocol_sha256'] == sha(remaining_root / 'protocol.json')
    assert all(sha(Path(path)) == digest for path, digest in remaining_protocol['frozen'].items())
    assert len(remaining['commands']) == 62 and all(command['exit_code'] == 0 for command in remaining['commands'])
    for command in remaining['commands']:
      assert sha(remaining_root / (command['name'] + '.log')) == command['stdout_sha256']
      assert sha(remaining_root / (command['name'] + '.stderr')) == command['stderr_sha256']
    for key in ('old_study', 'mean_study'):
      parent = Path(protocol[key])
      assert (parent / 'report.json').is_file()
      assert str((parent / 'report.json').resolve()) in protocol['frozen']

    cases = Path(protocol['validation_cases'])
    assert sha(cases) == protocol['validation_cases_sha256']
    case_lines = cases.read_text().splitlines()
    assert len(case_lines) == 200
    ids = [tuple(map(int, line.split()[:2] + [line.split()[3]])) for line in case_lines]
    assert len({entry[2] for entry in ids}) == 200
    assert [sum(entry[1] == group for entry in ids) for group in range(5)] == [40] * 5

    assert [model['seed'] for model in report['models']] == list(SEEDS)
    assert all(model['configuration'] == 'midl_mean4' and model['final_version'] == 8192
               and len(model['chunks']) == len(TARGETS) for model in report['models'])
    for model in report['models']:
      assert sha(Path(model['path'])) == model['sha256']
      assert sha(Path(model['policy'])) == model['policy_sha256']
      assert sha(Path(model['provenance_manifest'])) == model['provenance_sha256']
      assert sha(Path(model['starts'])) == model['starts_sha256']
      assert [chunk['version'] for chunk in model['chunks']] == list(TARGETS)

    rows42 = checked_rows(root / 'validation-midl_mean4-42.log', ids)
    cells = [validation_cell(42, rows42)]
    for seed in REMAINING_SEEDS:
      rows = checked_rows(remaining_root / ('validation-midl_mean4-' + str(seed) + '.log'), ids)
      cells.append(validation_cell(seed, rows))
    assert cells == report['validation']
    total = sum(cell['goals'] for cell in cells)
    groups = [sum(cell['groups'][group] for cell in cells) for group in range(5)]
    gates = dict(mean=total >= 970, every_seed=all(cell['goals'] >= 180 for cell in cells),
        groups=all(value >= 180 for value in groups),
        cooperation=all(cell['passes'] >= 40 and cell['joint'] >= 40 for cell in cells))
    assert gates == report['gates'] and all(gates.values()) == report['validation_passed']
    assert total / 1000 == report['candidate_mean']
    assert [value / 200 for value in groups] == report['candidate_group_means']
    command = report['commands']
    assert len(command) == 1 and command[0]['name'] == 'validation-midl_mean4-42' and command[0]['exit_code'] == 0
    assert sha(root / 'validation-midl_mean4-42.log') == command[0]['stdout_sha256']
    assert sha(root / 'validation-midl_mean4-42.stderr') == command[0]['stderr_sha256']
    assert report['imported'] == dict(recovery_report_sha256=sha(recovery_root / 'report.json'),
        recovery_audit_sha256=sha(Path(protocol['recovery_audit']) / 'report.json'),
        remaining_report_sha256=sha(remaining_root / 'report.json'))
    result.update(passed=True, validation_passed=all(gates.values()), candidate_accepted=False,
        gates=gates, candidate_mean=total / 1000, candidate_group_means=[value / 200 for value in groups],
        validation=cells, report_sha256=sha(root / 'report.json'), protocol_sha256=sha(root / 'protocol.json'),
        source_sha256=protocol['source']['sha256'], auditor_sha256=sha(Path(__file__)))
  except BaseException as error:
    result['error'] = f'{type(error).__name__}: {error}'
  (out / 'report.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
  print(json.dumps(result), flush=True)
  return 0 if result['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
