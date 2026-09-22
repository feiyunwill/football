#!/usr/bin/env python3
"""Archive bounded saves, real persistence and process-interruption evidence."""
import argparse
import ast
import faulthandler
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[2]


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  os.chdir(ROOT)
  sys.path.insert(0, str(ROOT))
  faulthandler.enable()
  faulthandler.dump_traceback_later(90, exit=True)
  warnings.simplefilter('always', ResourceWarning)
  requirements = {'SaveBudgetTest': 14, 'ProgressBudgetTest': 6, 'SaveDiskTest': 15}
  suite, groups = unittest.TestSuite(), {}
  for name in requirements:
    tests = unittest.defaultTestLoader.loadTestsFromName('gfootball.frame_sync.test_save_budget.' + name)
    groups[name] = tests.countTestCases()
    suite.addTests(tests)
  log = output / 'tests.log'
  with log.open('w', encoding='utf-8') as stream:
    previous_stderr, sys.stderr = sys.stderr, stream
    try:
      result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
      gc.collect()
    finally:
      sys.stderr = previous_stderr
      faulthandler.cancel_dump_traceback_later()
  from gfootball.recording_directory import _lock_descriptors
  remaining = [thread.name for thread in threading.enumerate() if thread.name.startswith('football-save-')]
  processes = [process.pid for process in (getattr(subprocess, '_active', None) or []) if process.poll() is None]
  log_text = log.read_text(encoding='utf-8')
  observed = [marker for marker in ('ResourceWarning:', 'Exception ignored in:', 'Exception in thread',
                                    'Task exception was never retrieved') if marker in log_text]
  sources = {'.project/checks/python_save_probe.py'}
  for module in list(sys.modules.values()):
    filename = getattr(module, '__file__', None)
    if filename:
      path = Path(filename).resolve()
      if path.suffix == '.py' and path.is_relative_to(ROOT):
        sources.add(path.relative_to(ROOT).as_posix())
  for name in sources:
    compile((ROOT / name).read_text(encoding='utf-8'), name, 'exec')
  compatible = ['gfootball/frame_sync/' + name + '.py' for name in ('save_system', 'save_data', 'save_runtime', 'save_store')]
  compatible += ['gfootball/recording_errors.py', 'gfootball/recording_directory.py']
  for name in compatible:
    ast.parse((ROOT / name).read_text(encoding='utf-8'), name, feature_version=(3, 9))
  sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
  report = dict(scope='Bounded immutable save records, validated progress, actual atomic files, process crashes and conflicting writers',
      native_GameEnv_executed=False, rendered_match_executed=False, cloud_sync_executed=False,
      formal_linux_acceptance=False, posix_directory_fsync_executed=os.name != 'nt',
      power_loss_executed=False, Python39_runtime_executed=False,
      passed=result.wasSuccessful() and not result.skipped and not remaining and not processes
      and not _lock_descriptors and not observed and all(groups[name] == count for name, count in requirements.items()),
      tests=result.testsRun, groups=groups, skipped=len(result.skipped),
      failures=[dict(test=str(test), traceback=traceback) for test, traceback in result.failures],
      errors=[dict(test=str(test), traceback=traceback) for test, traceback in result.errors],
      remaining_owned_threads=remaining, remaining_tracked_subprocesses=processes,
      remaining_owned_lock_descriptors=sorted(_lock_descriptors), observed_failure_markers=observed,
      python39_syntax_checked=compatible, python=sys.version, executable=sys.executable,
      platform=platform.platform(), log_sha256=sha(log),
      sources={name: sha(ROOT / name) for name in sorted(sources)})
  (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
  print(json.dumps({key: value for key, value in report.items() if key != 'sources'}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
