"""Run the pre-registered first-action intervention diagnosis for rejected Schema14."""
import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

import quality
from validate import ROOT, sha, source_fingerprint

SEEDS = (42, 123, 2026, 31415, 271828)
SELECTED = (14, 17, 25, 127, 152, 163, 173, 175, 191, 193, 194)


def read(path):
  return json.loads(path.read_text())


def rows(path):
  return [json.loads(line) for line in path.read_text().splitlines()]


def write(path, value):
  path.write_text(json.dumps(value, indent=2) + '\n')


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  for key in ('quality', 'build', 'study', 'audit', 'diagnosis', 'output'):
    parser.add_argument('--' + key, type=Path, required=True)
  args = parser.parse_args()
  quality_receipt = quality.verify(args.quality / 'report.json')
  before = source_fingerprint()
  study, audit, diagnosis = (args.study.resolve(), args.audit.resolve(), args.diagnosis.resolve())
  report, audit_report, diagnosis_report = read(study / 'report.json'), read(audit / 'report.json'), read(diagnosis / 'report.json')
  assert report['passed'] and report['validation_passed'] is False
  assert audit_report['passed'] and audit_report['validation_passed'] is False
  assert report['source_before'] == report['source_after'] == before
  assert audit_report['source_sha256'] == before['sha256']
  assert diagnosis_report['passed'] and tuple(item['index'] for item in diagnosis_report['universal_failures']) == SELECTED
  cases = Path(diagnosis_report['cases']).resolve()
  assert sha(cases) == diagnosis_report['cases_sha256']
  models = {row['seed']: Path(row['policy']).resolve() for row in report['models']}
  assert tuple(sorted(models)) == SEEDS
  out = args.output.resolve()
  out.mkdir(parents=True, exist_ok=False)
  (out / 'selected.txt').write_text(''.join(f'{index}\n' for index in SELECTED))
  build = args.build.resolve()
  flags = {}
  for line in (build / 'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
    if ' = ' in line:
      key, value = line.split(' = ', 1)
      flags[key] = shlex.split(value)
  link = shlex.split((build / 'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
  helper = Path(__file__).with_name('trace_o23_schema14_first_action_interventions.cpp')
  obj, binary = out / 'trace.o', out / 'trace'
  compile_cmd = [link[0], *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], *flags['CXX_FLAGS'], '-c', str(helper), '-o', str(obj)]
  subprocess.run(compile_cmd, cwd=build, check=True)
  positions = [index for index, item in enumerate(link) if item.endswith('native_ppo_train.cpp.o')]
  assert len(positions) == 1
  link[positions[0]] = str(obj)
  link[link.index('-o') + 1] = str(binary)
  subprocess.run(link, cwd=build, check=True)
  expected = {}
  logs = []
  for seed in SEEDS:
    log = study / f'validation-entropy_high_finisher_mean4-{seed}.log'
    values = rows(log)[:-1]
    expected[seed] = {row['index']: row for row in values if row['index'] in SELECTED}
    assert tuple(expected[seed]) == SELECTED and all(row['controlled_score_delta'] <= 0 for row in expected[seed].values())
    logs.append(log)
  frozen_paths = [Path(__file__), helper, binary, build / 'bin/native_ppo_train', build / 'libfootball_engine.so', cases, study / 'report.json', audit / 'report.json', diagnosis / 'report.json', *logs, *models.values()]
  frozen = {str(path.resolve()): sha(path) for path in frozen_paths}
  protocol = dict(scope='Causal first-action intervention diagnosis only; no candidate selection, training, confirmation, O24, or O25.', source=before, quality=quality_receipt, study=str(study), audit=str(audit), diagnosis=str(diagnosis), cases=str(cases), selected=list(SELECTED), seeds=list(SEEDS), treatments=list(range(19)), baseline_forced_first_action=-1, continuation='sample policy action first to consume the original action RNG draw; apply treatment only on step zero; continue with that controller state.', helper_build=dict(compile=compile_cmd, link=link, trace_sha256=sha(binary)), frozen=frozen)
  write(out / 'protocol.json', protocol)
  env = dict(os.environ, LD_LIBRARY_PATH=str(build), GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'), GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  commands, summary = [], {}
  try:
    for seed in SEEDS:
      log, error = out / f'interventions-{seed}.jsonl', out / f'interventions-{seed}.stderr'
      run = subprocess.run([binary, models[seed], cases, out / 'selected.txt'], cwd=build, env=env, capture_output=True, text=True, timeout=300)
      log.write_text(run.stdout)
      error.write_text(run.stderr)
      assert run.returncode == 0 and not run.stderr
      values = rows(log)
      assert len(values) == len(SELECTED) * 20
      by_case = {index: [row for row in values if row['index'] == index] for index in SELECTED}
      assert all(len(cells) == 20 and [row['forced_first_action'] for row in cells] == [-1, *range(19)] for cells in by_case.values())
      baselines = {index: cells[0] for index, cells in by_case.items()}
      for index, baseline in baselines.items():
        known = expected[seed][index]
        assert (baseline['score'] > 0) == (known['controlled_score_delta'] > 0)
        assert baseline['completed_passes'] == known['completed_passes']
        assert baseline['forced_first_action'] == -1 and baseline['sampled_first_action'] == baseline['applied_first_action']
      goals_by_action = {str(action): sum(cells[action + 1]['score'] > 0 for cells in by_case.values()) for action in range(19)}
      summary[str(seed)] = dict(baseline_goals=sum(row['score'] > 0 for row in baselines.values()), forced_goals=goals_by_action, action_effect_observed=any(goals_by_action.values()))
      commands.append(dict(seed=seed, exit_code=run.returncode, stdout_sha256=sha(log), stderr_sha256=sha(error)))
      assert source_fingerprint() == before and all(sha(Path(path)) == digest for path, digest in frozen.items())
    result = dict(passed=True, source_before=before, source_after=source_fingerprint(), protocol_sha256=sha(out / 'protocol.json'), commands=commands, summary=summary, hypothesis_falsified=not any(item['action_effect_observed'] for item in summary.values()))
  except BaseException as error:
    result = dict(passed=False, error=f'{type(error).__name__}: {error}', source_before=before, source_after=source_fingerprint(), commands=commands)
  write(out / 'report.json', result)
  print(json.dumps({key: result.get(key) for key in ('passed', 'hypothesis_falsified', 'error')}), flush=True)
  return 0 if result['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
