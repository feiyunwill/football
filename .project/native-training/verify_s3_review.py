#!/usr/bin/env python3
"""Current-source S3 evidence audit and real stopped-worker kill escalation."""
import argparse
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import signal
import time

from validate import ROOT, source_fingerprint
from gfootball.training_workers import NativeWorkerPool, WorkerError


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--build-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  evidence = ROOT / '.project/native-training/evidence'
  report = {'passed': False, 'source_before': source_fingerprint(), 'checks': []}
  report['reviewer_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
  try:
    # Historical evidence remains bound to its own manifest, not relabeled current.
    for name in ('nt-3.1-integration-20261015-a', 'nt-3.2-candidate-integration-20261015-a',
                 'nt-3.2-restored-integration-20261015-a', 'nt-3.3-integration-20261015-b',
                 'nt-3.4-integration-20261015-a'):
      folder = evidence / name
      data = json.loads((folder / 'report.json').read_text())
      if not data['passed'] or data['source_before'] != data['source_after']:
        raise RuntimeError(f'Invalid historical integration evidence: {name}')
      for command in data['commands']:
        if command['exit_code'] != 0 or hashlib.sha256((folder / command['log']).read_bytes()).hexdigest() != command['sha256']:
          raise RuntimeError(f'Log hash/status mismatch: {name}/{command["name"]}')
      report['checks'].append({'integration': name, 'source': data['source_after']['sha256'],
                                'verified_logs': len(data['commands'])})
    current = json.loads((evidence / 'nt-3.4-integration-20261015-a/report.json').read_text())
    measured = json.loads((evidence / 'nt-3.4-workers-20261015-b/report.json').read_text())
    if (not measured['passed'] or measured['source_before'] != measured['source_after']
        or current['source_after'] != report['source_before'] or measured['source_after'] != report['source_before']):
      raise RuntimeError('Current integration/measurement source mismatch')
    stage = args.build_root.resolve() / 'validation-stage/gfootball_engine'
    for name, digest in current['artifacts'].items():
      if hashlib.sha256((stage / name).read_bytes()).hexdigest() != digest or measured['artifacts'][name] != digest:
        raise RuntimeError('Staged artifact mismatch')
    if hashlib.sha256((evidence / 'nt-3.4-workers-20261015-b/workers.log').read_bytes()).hexdigest() != measured['command']['sha256']:
      raise RuntimeError('Worker measurement log hash mismatch')
    data = json.loads((evidence / 'nt-3.4-workers-20261015-b/workers.json').read_text())
    configurations = set()
    reference = {}
    for workload in data['workloads']:
      key = (workload['players'], workload['cadence'])
      configurations.add((*key, workload['workers']))
      if len(workload['samples']) != 3: raise RuntimeError('Missing repeated sample')
      for sample in workload['samples']:
        collected = sample['collection']
        if key not in reference: reference[key] = collected['episodes']
        if collected['episodes'] != reference[key]: raise RuntimeError('Cross-worker episode mismatch')
        if collected['transitions'] != sum(row['steps'] for row in collected['episodes']):
          raise RuntimeError('Transition count mismatch')
        if sample['parent_fds_before'] != sample['parent_fds_after'] or sample['exit_codes'] != [0] * workload['workers']:
          raise RuntimeError('Recorded cleanup mismatch')
    if configurations != {(p, c, w) for p in (1, 11) for c in (2, 10) for w in (1, 2, 4)}:
      raise RuntimeError('Missing worker scaling configuration')
    report['checks'].append({'current_source_artifacts_logs_and_36_samples': True})
    kwargs = {'env_name': 'academy_empty_goal_close',
              'other_config_options': {'render_resolution_x': 160, 'render_resolution_y': 90}}
    with NativeWorkerPool(kwargs) as warmup:
      warmup.reset({0: 0})
    baseline_fds = len(os.listdir('/proc/self/fd'))
    baseline_children = {child.pid for child in multiprocessing.active_children()}
    pool = NativeWorkerPool(kwargs, timeout=0.2)
    try:
      pool.reset({0: 0})
      pid = pool.worker_pids[0]
      os.kill(pid, signal.SIGSTOP)
      deadline = time.monotonic() + 1
      while (Path('/proc') / str(pid) / 'stat').read_text().rpartition(') ')[2][0] != 'T':
        if time.monotonic() > deadline: raise RuntimeError('Worker did not stop')
        time.sleep(0.01)
      start = time.monotonic()
      try:
        pool.step({0: 0})
      except WorkerError as error:
        if 'deadline' not in str(error): raise
      else:
        raise RuntimeError('Stopped worker did not time out')
      elapsed = time.monotonic() - start
      if (elapsed > 5 or pool.exit_codes != (-signal.SIGKILL,) or not pool.closed
          or Path('/proc', str(pid)).exists()):
        raise RuntimeError('Stop/terminate/kill escalation failed')
      report['checks'].append({'stopped_worker_deadline_kill_reap': True, 'seconds': elapsed,
                               'pid': pid, 'exit_codes': list(pool.exit_codes)})
    finally:
      pool.close()
    if (len(os.listdir('/proc/self/fd')) != baseline_fds
        or {child.pid for child in multiprocessing.active_children()} != baseline_children):
      raise RuntimeError('Stopped worker cleanup leaked resources')
    report.update(passed=True, error=None)
  except Exception as error:
    report['error'] = str(error)
  finally:
    report['source_after'] = source_fingerprint()
    if report['source_before'] != report['source_after']:
      report.update(passed=False, error='Source changed during review verification')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps({'passed': report['passed'], 'error': report.get('error')}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
