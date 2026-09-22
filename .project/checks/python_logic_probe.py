#!/usr/bin/env python3
"""Archive Python logic oracle, real TCP integration and transport regressions."""
import argparse
import faulthandler
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
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
  sys.path.insert(0, str(ROOT))
  os.chdir(ROOT)
  faulthandler.enable()
  faulthandler.dump_traceback_later(90, exit=True)
  warnings.simplefilter('always', ResourceWarning)
  requirements = {
      # 2026-09-09: add strict work/lifetime guards and 2,000-frame oracle runs.
      # 'test_client_logic_budget.LogicBudgetTest': 21,
      # 2026-09-09: add correction-root exception recovery and loop reentry.
      # 'test_client_logic_budget.LogicBudgetTest': 24,
      # 2026-09-09: exact input retry rate, frame identity and timestamp refund.
      # 'test_client_logic_budget.LogicBudgetTest': 25,
      'test_client_logic_budget.LogicBudgetTest': 26,
      # 2026-09-09: verify the legacy server's current-frame-only input policy.
      # 'test_client_logic_budget.LogicTCPTest': 1,
      'test_client_logic_budget.LogicTCPTest': 2,
      'test_client_logic_budget.LogicAsyncTCPTest': 1,
      'test_tcp_client_budget.BufferBudgetTest': 7,
      'test_tcp_client_budget.TCPClientBudgetTest': 13,
      'test_tcp_client_budget.AsyncTCPClientBudgetTest': 12,
  }
  suite = unittest.TestSuite()
  groups = {}
  for name in requirements:
    part = unittest.defaultTestLoader.loadTestsFromName('gfootball.frame_sync.' + name)
    groups[name] = part.countTestCases()
    suite.addTests(part)
  log = output / 'tests.log'
  with log.open('w', encoding='utf-8') as stream:
    previous_stderr = sys.stderr
    sys.stderr = stream
    try:
      result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
      gc.collect()
    finally:
      sys.stderr = previous_stderr
      faulthandler.cancel_dump_traceback_later()
  remaining = [thread.name for thread in threading.enumerate()
               if thread.name.startswith(('football-tcp-', 'tcp-budget-'))]
  text = log.read_text(encoding='utf-8')
  sources = [
      'gfootball/frame_sync/client_buffers.py', 'gfootball/frame_sync/client_tcp.py',
      'gfootball/frame_sync/client.py', 'gfootball/frame_sync/client_logic.py',
      'gfootball/frame_sync/protocol.py', 'gfootball/frame_sync/config.py',
      'gfootball/frame_sync/client_async.py', 'gfootball/frame_sync/client_tcp_async.py',
      'gfootball/frame_sync/test_tcp_client_budget.py',
      'gfootball/frame_sync/test_client_logic_budget.py', '.project/checks/python_logic_probe.py',
  ]
  sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
  report = dict(
      scope='Python logic with deterministic state-machine oracle, real sync/async TCP and transport regression; no GameEnv',
      passed=result.wasSuccessful() and all(groups[name] >= count for name, count in requirements.items())
      and not result.skipped and not remaining and not any(marker in text for marker in (
          'ResourceWarning:', 'Task exception was never retrieved', 'Task was destroyed but it is pending',
          'Exception in callback', 'Exception ignored in:')),
      tests=result.testsRun, groups=groups, skipped=len(result.skipped),
      failures=[dict(test=str(test), traceback=traceback) for test, traceback in result.failures],
      errors=[dict(test=str(test), traceback=traceback) for test, traceback in result.errors],
      remaining_owned_threads=remaining, log_sha256=sha(log), python=sys.version,
      executable=sys.executable, platform=platform.platform(),
      sources={path: sha(ROOT / path) for path in sources})
  (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
  print(json.dumps(report, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
