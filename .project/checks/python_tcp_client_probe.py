#!/usr/bin/env python3
"""Archive actual Python TCP capacity tests without requiring the native engine."""
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
  suite = unittest.defaultTestLoader.loadTestsFromName('gfootball.frame_sync.test_tcp_client_budget')
  groups = {name: unittest.defaultTestLoader.loadTestsFromName(
      'gfootball.frame_sync.test_tcp_client_budget.' + name).countTestCases()
      for name in ('BufferBudgetTest', 'TCPClientBudgetTest', 'AsyncTCPClientBudgetTest')}
  # 2026-09-09: include the real transport failure -> logic stop contract.
  # required = dict(BufferBudgetTest=7, TCPClientBudgetTest=12, AsyncTCPClientBudgetTest=12)
  required = dict(BufferBudgetTest=7, TCPClientBudgetTest=13, AsyncTCPClientBudgetTest=12)
  log = output / 'tests.log'
  with log.open('w', encoding='utf-8') as stream:
    # Keep diagnostics from resource finalizers alongside the test report.
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
  sources = ['gfootball/frame_sync/client_buffers.py', 'gfootball/frame_sync/client_tcp.py',
             'gfootball/frame_sync/client.py', 'gfootball/frame_sync/protocol.py',
             'gfootball/frame_sync/client_async.py', 'gfootball/frame_sync/client_tcp_async.py',
             'gfootball/frame_sync/test_tcp_client_budget.py', '.project/checks/python_tcp_client_probe.py']
  sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
  # 2026-09-09: include the real asyncio transport and lifecycle contracts.
  # report = dict(scope='shared buffers and actual Python synchronous TCP transport; no GameEnv',
  report = dict(scope='shared buffers and actual Python synchronous/asynchronous TCP transports; no GameEnv',
                # 2026-09-09: require all three tested surfaces, not just the old sync count.
                # passed=result.wasSuccessful() and result.testsRun >= 17 and not result.skipped
                # and not remaining and 'ResourceWarning:' not in text,
                passed=result.wasSuccessful() and all(groups[name] >= count for name, count in required.items())
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
