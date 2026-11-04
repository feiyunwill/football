"""Compare a frozen schema7 low-LR validation log with frozen broad80 evidence."""
import argparse
import json
from pathlib import Path


def read_rows(path):
  rows = [json.loads(line) for line in path.read_text().splitlines()]
  summary = rows.pop()
  assert summary['complete'] and len(rows) == 200
  return rows


def won(row):
  return row['controlled_score_delta'] > 0


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--lowlr-study', type=Path, required=True)
  parser.add_argument('--broad-study', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--seed', type=int, default=271828)
  args = parser.parse_args()
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  lowlr = read_rows(args.lowlr_study / f'validation-lowlr_mean4-{args.seed}.log')
  broad = read_rows(args.broad_study / f'validation-broad80-{args.seed}.log')
  ids = [(row['index'], row['group'], row['engine_seed']) for row in broad]
  assert ids == [(row['index'], row['group'], row['engine_seed']) for row in lowlr]
  groups = []
  for group in range(5):
    pairs = [(old, new) for old, new in zip(broad, lowlr) if old['group'] == group]
    groups.append(dict(
        group=group,
        broad_success=sum(won(old) for old, _ in pairs),
        lowlr_success=sum(won(new) for _, new in pairs),
        old_only_success=sum(won(old) and not won(new) for old, new in pairs),
        new_only_success=sum(not won(old) and won(new) for old, new in pairs),
        both_failed=sum(not won(old) and not won(new) for old, new in pairs)))
  old_only = []
  for old, new in zip(broad, lowlr):
    if won(old) and not won(new):
      old_only.append(dict(
          index=old['index'], group=old['group'], engine_seed=old['engine_seed'],
          start_x=old['start_x'], start_y=old['start_y'],
          broad_steps=old['steps'], lowlr_steps=new['steps'],
          lowlr_completed_passes=new['completed_passes'], lowlr_turnovers=new['turnovers']))
  result = dict(
      passed=True,
      scope='frozen validation diagnosis only; no candidate selection or training',
      seed=args.seed,
      episode_ids_equal=True,
      broad_success=sum(won(row) for row in broad),
      lowlr_success=sum(won(row) for row in lowlr),
      old_only_success=len(old_only),
      new_only_success=sum(not won(old) and won(new) for old, new in zip(broad, lowlr)),
      groups=groups,
      old_only_cases=old_only)
  (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
  print(json.dumps(result))


if __name__ == '__main__':
  main()
