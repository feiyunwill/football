"""Register a fresh, deterministic Schema14 acceptance case set before training."""
import argparse
import hashlib
import json
import random
from pathlib import Path


def bounded(rng, lo, hi):
  return lo + (hi - lo) * rng.random()


def case(rng, index, group):
  seed = rng.randrange(1, 2_000_000_001)
  action_seed = rng.randrange(1, 2**63)
  ax, ay, gap = bounded(rng, .44, .68), bounded(rng, -.22, .22), bounded(rng, .12, .20)
  if group == 1:
    ax = bounded(rng, .28, .44)
  if group == 2:
    ay = (-1 if rng.randrange(2) == 0 else 1) * bounded(rng, .22, .34)
  if group == 3:
    gap = bounded(rng, .06, .12)
  tx, ty = ax + bounded(rng, .08, .18), (-1 if ay > 0 else 1) * bounded(rng, .12, .26)
  if group == 4:
    tx, ty = ax + bounded(rng, .025, .21), bounded(rng, -.32, .32)
    if abs(ty - ay) < .08:
      ty = -.24 if ay >= 0 else .24
  dx, dy = ax + gap, ay * .25 + bounded(rng, -.06, .06)
  return (index, group, 0, seed, action_seed, ax, ay, tx, ty, dx, dy)


def sha(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  out = args.output.resolve()
  out.mkdir(parents=True, exist_ok=False)
  rng_seed = 2026102914
  rng = random.Random(rng_seed)
  rows = [case(rng, index, index // 40) for index in range(200)]
  assert [row[1] for row in rows] == [group for group in range(5) for _ in range(40)]
  assert len({row[3] for row in rows}) == 200
  cases = out / 'cases.txt'
  cases.write_text(''.join(' '.join(format(value, '.17g') if isinstance(value, float) else str(value) for value in row) + '\n' for row in rows))
  digest = sha(cases)
  prior = {
      'schema11': Path('/root/work_space/football-artifacts/work-o23-schema11-edge-balanced-finisher-cases-20261028-b/cases.txt'),
      'schema12': Path('/root/work_space/football-artifacts/work-o23-schema12-entropy-stable-finisher-cases-20261028-a/cases.txt'),
      'schema13': Path('/root/work_space/football-artifacts/work-o23-schema13-entropy-midpoint-finisher-cases-20261029-a/cases.txt'),
  }
  prior_sha256 = {name: sha(path) for name, path in prior.items()}
  assert digest not in prior_sha256.values()
  report = dict(
      passed=True,
      purpose='Schema14 independent acceptance only; generated after the audited pilot and budget, before the five-seed study.',
      generator='register_o23_schema14_entropy_high_finisher_cases.py',
      generator_seed=rng_seed,
      cases=200,
      groups={str(group): 40 for group in range(5)},
      case_sha256=digest,
      excluded_prior_case_sha256=prior_sha256,
      file=str(cases))
  (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps(report), flush=True)


if __name__ == '__main__':
  main()
