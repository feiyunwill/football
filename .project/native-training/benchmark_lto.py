#!/usr/bin/env python3
"""LTO experiment: alternate isolated baseline/candidate engine-step processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
from validate import ROOT, source_fingerprint

parser = argparse.ArgumentParser()
parser.add_argument('--python', required=True)
parser.add_argument('--baseline', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--steps', type=int, default=512)
parser.add_argument('--repeats', type=int, default=8)
parser.add_argument('--primary-only', action='store_true',
                    help='Screen the pre-registered 11-player/cadence2/predetermined primary before the full matrix')
parser.add_argument('--primary-report', type=Path, help='Reuse the completed primary screen; do not repeat its eight pairs')
args = parser.parse_args()
if args.primary_only and args.primary_report: parser.error('Choose a primary screen or reuse, not both')
if not 32 <= args.steps <= 1024 or not 4 <= args.repeats <= 20: parser.error('Invalid comparison budget')
output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
stages = {'baseline':args.baseline.resolve(), 'candidate':args.candidate.resolve()}
report = {'passed':False, 'source_before':source_fingerprint(), 'workloads':[], 'commands':[]}
report['scope'] = 'primary_only' if args.primary_only else 'full_matrix'
report['validator_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
report['probe_sha256'] = hashlib.sha256((ROOT / '.project/native-training/benchmark_candidate_rollout.py').read_bytes()).hexdigest()
report['artifacts'] = {variant:{name:hashlib.sha256((stage / 'gfootball_engine' / name).read_bytes()).hexdigest()
                              for name in ('_gameplayfootball.so', 'libfootball_engine.so')}
                       for variant,stage in stages.items()}
report['baseline_manifest'] = json.loads((stages['baseline'] / 'baseline.json').read_text())

def run(variant, players, cadence, feedback, verify, name):
  stage = stages[variant]
  env = dict(os.environ, PYTHONPATH=str(stage) + os.pathsep + str(ROOT),
             GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'), GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  command = [args.python, str(ROOT / '.project/native-training/benchmark_candidate_rollout.py'),
             '--players',str(players), '--cadence',str(cadence), '--steps',str(128 if verify else args.steps),
             '--output',str(output / (name + '.json'))]
  if feedback: command.append('--feedback')
  if verify: command.append('--verify')
  result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=180)
  log = result.stdout + result.stderr; (output / (name + '.log')).write_bytes(log)
  report['commands'].append({'argv':command, 'variant':variant, 'exit_code':result.returncode,
                             'sha256':hashlib.sha256(log).hexdigest()})
  if result.returncode: raise RuntimeError('Comparison process failed: ' + name)
  data = json.loads((output / (name + '.json')).read_text())
  expected = (stage / 'gfootball_engine/_gameplayfootball.so').resolve()
  if Path(data['loaded_module']) != expected: raise RuntimeError('Wrong extension loaded')
  return data

try:
  verified_cases = {}
  if args.primary_only:
    # Verify the complete trajectory matrix before any timed samples.
    for p in (1, 11):
      for c in (2, 10):
        for f in (False, True):
          key = f'{p},{c},{int(f)}'
          verified = {v:run(v,p,c,f,True,f'preverify-p{p}-c{c}-f{int(f)}-'+v) for v in stages}
          if verified['baseline']['trajectory_sha256'] != verified['candidate']['trajectory_sha256']:
            raise RuntimeError('Trajectory mismatch before timing: '+key)
          verified_cases[key] = verified
    report['all_case_verified_trajectories'] = verified_cases
  if args.primary_report:
    prior = json.loads(args.primary_report.read_text())
    if not (prior['passed'] and prior['scope'] == 'primary_only' and len(prior['workloads']) == 1
            and prior['source_before'] == prior['source_after'] == report['source_before']
            and prior['artifacts'] == report['artifacts']
            and prior['probe_sha256'] == report['probe_sha256']):
      raise RuntimeError('Primary-screen identity changed')
    verified_cases = prior['all_case_verified_trajectories']
    if len(verified_cases) != 8: raise RuntimeError('Incomplete pre-timing trajectory matrix')
    report['all_case_verified_trajectories'] = verified_cases
    report['workloads'].extend(prior['workloads'])
    report['primary_screen'] = {'path':str(args.primary_report.resolve()),
        'sha256':hashlib.sha256(args.primary_report.read_bytes()).hexdigest()}
  for players in (1, 11):
    for cadence in (2, 10):
      for feedback in (False, True):
        if args.primary_only and (players, cadence, feedback) != (11, 2, False): continue
        if args.primary_report and (players, cadence, feedback) == (11, 2, False): continue
        prefix = f'p{players}-c{cadence}-feedback{int(feedback)}'
        print(prefix, flush=True)
        key = f'{players},{cadence},{int(feedback)}'
        verified = verified_cases.get(key)
        if verified is None:
          verified = {v:run(v, players,cadence,feedback,True,prefix + '-verify-' + v) for v in stages}
        if verified['baseline']['trajectory_sha256'] != verified['candidate']['trajectory_sha256']:
          raise RuntimeError('Per-step observations/rewards/kernel state changed: ' + prefix)
        samples = {v:[] for v in stages}; cpu_samples = {v:[] for v in stages}; digest = None
        for repeat in range(args.repeats):
          order = ('baseline','candidate') if repeat % 2 == 0 else ('candidate','baseline')
          for variant in order:
            data = run(variant, players,cadence,feedback,False,f'{prefix}-r{repeat}-{variant}')
            if digest is None: digest = data['final_sha256']
            if digest != data['final_sha256']: raise RuntimeError('Timed rollout state changed')
            samples[variant].append(data['elapsed_ns'])
            cpu_samples[variant].append(data['cpu_ns'])
        ratios = [a / b for a,b in zip(samples['baseline'], samples['candidate'])]
        cpu_ratios = [a / b for a,b in zip(cpu_samples['baseline'], cpu_samples['candidate'])]
        report['workloads'].append({'players':players,'cadence':cadence,'feedback':feedback,
                                    'samples_ns':samples,'paired_speedups':ratios,
                                    'median_speedup':statistics.median(ratios), 'final_sha256':digest,
                                    'cpu_samples_ns':cpu_samples, 'paired_cpu_speedups':cpu_ratios,
                                    'median_cpu_speedup':statistics.median(cpu_ratios), 'cpu_affinity':data['cpu_affinity'],
                                    'verified_trajectory_sha256':verified['baseline']['trajectory_sha256']})
  report['passed'] = True; report['error'] = None
except Exception as error:
  report['error'] = str(error)
finally:
  report['source_after'] = source_fingerprint()
  if report['source_before'] != report['source_after']: report.update(passed=False,error='Source changed during comparison')
  (output / 'report.json').write_text(json.dumps(report,indent=2) + '\n')
print(json.dumps({'passed':report['passed'],'error':report.get('error')},indent=2))
raise SystemExit(0 if report['passed'] else 1)
