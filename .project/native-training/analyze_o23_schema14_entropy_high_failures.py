"""Reproducibly summarize cross-seed failures from the rejected Schema14 study."""
import argparse
import hashlib
import json
from pathlib import Path


SEEDS = (42, 123, 2026, 31415, 271828)


def read(path):
  return json.loads(path.read_text())


def sha(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--study', type=Path, required=True)
  parser.add_argument('--cases', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  study, cases, out = args.study.resolve(), args.cases.resolve(), args.output.resolve()
  out.mkdir(parents=True, exist_ok=False)
  report = read(study / 'report.json')
  assert report['passed'] and report['validation_passed'] is False
  assert report['gates'] == dict(mean=False, every_seed=True, groups=False, cooperation=True)
  geometry = {}
  for line in cases.read_text().splitlines():
    values = line.split()
    index, group = map(int, values[:2])
    geometry[index] = dict(group=group, engine_seed=int(values[3]), action_seed=int(values[4]),
                           attacker=[float(values[5]), float(values[6])], teammate=[float(values[7]), float(values[8])],
                           defender=[float(values[9]), float(values[10])])
  assert len(geometry) == 200 and {cell['group'] for cell in geometry.values()} == set(range(5))
  observations = {index: [] for index in geometry}
  logs = {}
  for seed in SEEDS:
    path = study / f'validation-entropy_high_finisher_mean4-{seed}.log'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    summary = rows.pop()
    assert summary['complete'] and len(rows) == 200
    assert [row['index'] for row in rows] == list(range(200))
    goals = sum(row['controlled_score_delta'] > 0 for row in rows)
    expected = next(cell for cell in report['validation'] if cell['seed'] == seed)
    assert goals == expected['goals']
    logs[str(seed)] = sha(path)
    for row in rows:
      observations[row['index']].append(dict(seed=seed, goal=row['controlled_score_delta'] > 0,
                                             completed_passes=row['completed_passes']))
  universal, variable = [], []
  group_totals = []
  for group in range(5):
    rows = [observations[index] for index, case in geometry.items() if case['group'] == group]
    group_totals.append(dict(group=group, goals=sum(item['goal'] for row in rows for item in row), episodes=len(rows) * len(SEEDS)))
  for index, rows in observations.items():
    failures = sum(not row['goal'] for row in rows)
    entry = dict(index=index, failures=failures, passes=sum(row['completed_passes'] > 0 for row in rows), **geometry[index])
    if failures == len(SEEDS):
      universal.append(entry)
    elif 2 <= failures < len(SEEDS):
      variable.append(entry)
  result = dict(passed=True,
                scope='Descriptive cross-seed diagnosis of rejected Schema14 validation logs; no causal action repair or successor selection.',
                study_report=str((study / 'report.json').resolve()), study_report_sha256=sha(study / 'report.json'),
                cases=str(cases), cases_sha256=sha(cases), logs=logs, seeds=list(SEEDS),
                candidate_mean=report['candidate_mean'], gates=report['gates'], group_totals=group_totals,
                universal_failures=universal, variable_failures=variable,
                conclusion='Groups 0 and 4 contain recurrent cross-seed failures. This is observational evidence only; it does not identify an action-level cause or authorize retuning.')
  (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
  print(json.dumps(dict(passed=True, universal_failures=len(universal), variable_failures=len(variable), group_totals=group_totals)), flush=True)


if __name__ == '__main__':
  main()
