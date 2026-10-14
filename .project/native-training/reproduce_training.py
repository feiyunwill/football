#!/usr/bin/env python3
"""One-command functional training/evaluation/resume reproduction, not a skill benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def sha(path):
  with path.open('rb') as stream:
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--program', type=Path, required=True, help='Native executable or package launcher')
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--seed', type=int, default=42)
  parser.add_argument('--updates', type=int, default=2)
  parser.add_argument('--split', type=int, default=1)
  parser.add_argument('--rollout', type=int, default=8)
  parser.add_argument('--timeout', type=int, default=600)
  args = parser.parse_args()
  program, output = args.program.resolve(), args.output.resolve()
  if output.exists() or not program.is_file():
    parser.error('Use an existing native program and a new output directory')
  if not (0 <= args.seed <= 2**64-1 and 1 <= args.split < args.updates <= 1024 and
          1 <= args.rollout <= 256 and 1 <= args.timeout <= 7200):
    parser.error('Invalid seed, split/update, rollout or timeout budget')
  output.mkdir(parents=True)
  report = dict(passed=False, program=str(program), script_sha256=sha(Path(__file__)), commands=[])
  common = ['--seed', str(args.seed), '--hidden', '8', '--epochs', '2', '--minibatch', '4',
            '--rollout', str(args.rollout), '--eval-episodes', '1', '--eval-steps', '16']
  full, prefix, resumed = [output / name for name in ('full.fppo', 'prefix.fppo', 'resumed.fppo')]
  try:
    records = []
    for name, options in [('full', ['--updates', str(args.updates), '--save', str(full)]),
                          ('prefix', ['--updates', str(args.split), '--save', str(prefix)]),
                          ('resume', ['--updates', str(args.updates-args.split), '--load', str(prefix), '--save', str(resumed)]),
                          ('frozen', ['--updates', '0', '--load', str(full)])]:
      command = [str(program), *common, *options]
      log = output / (name + '.json'); error = output / (name + '.stderr.log')
      start = time.monotonic()
      with log.open('wb') as stdout, error.open('wb') as stderr:
        process = subprocess.run(command, cwd=output, stdout=stdout, stderr=stderr,
                                 timeout=args.timeout, check=False)
      report['commands'].append(dict(name=name, argv=command, exit_code=process.returncode,
                                     seconds=time.monotonic()-start, log=log.name, sha256=sha(log),
                                     stderr=error.name, stderr_sha256=sha(error)))
      if process.returncode:
        raise RuntimeError(name + ' failed; see ' + str(error))
      records.append(json.loads(log.read_text()))
    baseline, beginning, continuation, frozen = records
    if baseline['iterations'][:args.split] != beginning['iterations'] or baseline['iterations'][args.split:] != continuation['iterations']:
      raise RuntimeError('Full and resumed update trajectories differ')
    if full.read_bytes() != resumed.read_bytes() or sha(full) != baseline['state_sha256']:
      raise RuntimeError('Full and resumed checkpoint bytes differ')
    if baseline['evaluation'] != continuation['evaluation'] or baseline['evaluation'] != frozen['evaluation']:
      raise RuntimeError('Frozen/resumed evaluation differs')
    if frozen['iterations'] or baseline['state_sha256'] != frozen['state_sha256']:
      raise RuntimeError('Frozen evaluation changed the full learner state')
    if not all(row['evaluation']['isolated'] for row in records):
      raise RuntimeError('Evaluation isolation failed')
    if not all(row['parameter_delta'] > 0 for row in baseline['iterations']):
      raise RuntimeError('Training did not change parameters')
    report.update(passed=True, checkpoint_sha256=sha(full), updates=baseline['version'],
                  transitions=baseline['total_transitions'],
                  scope='short functional reproduction; no convergence or football-skill claim')
  except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
    report['error'] = str(error)
  (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps(dict(passed=report['passed'], report=str(output / 'report.json'), error=report.get('error')), indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
