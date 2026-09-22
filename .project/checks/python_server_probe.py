#!/usr/bin/env python3
"""Archive real Python TCP server contracts and client/logic/presentation regressions."""
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
  parser.add_argument('--native', action='store_true', help='Also execute actual native GameEnv server/replica checks')
  args = parser.parse_args()
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  sys.path.insert(0, str(ROOT))
  os.chdir(ROOT)
  faulthandler.enable()
  # 2026-09-10: bound the optional real engine startup/match verification too.
  # faulthandler.dump_traceback_later(90, exit=True)
  faulthandler.dump_traceback_later(180 if args.native else 90, exit=True)
  warnings.simplefilter('always', ResourceWarning)
  requirements = {
      # 2026-09-10: real deadline/backpressure/close cancellation coverage.
      # 'test_server_budget.ServerStateTest': 8,
      # 'test_server_budget.SyncServerTest': 7,
      # 'test_server_budget.AsyncServerTest': 2,
      'test_server_budget.ServerStateTest': 9,
      # 2026-09-10: periodic bidirectional heartbeat, command cap and 22 peers.
      # 'test_server_budget.SyncServerTest': 13,
      # 'test_server_budget.AsyncServerTest': 4,
      'test_server_budget.SyncServerTest': 16,
      # 2026-09-10: shutdown rejects new engine work without awaiting cleanup.
      # 'test_server_budget.AsyncServerTest': 5,
      # 2026-09-10: reject native engine migration before opening a foreign socket.
      # 'test_server_budget.AsyncServerTest': 6,
      'test_server_budget.AsyncServerTest': 7,
      'test_presentation_budget.HolderBudgetTest': 14,
      'test_presentation_budget.RenderBudgetTest': 12,
      'test_presentation_budget.LogicPresentationTest': 2,
      'test_client_logic_budget.LogicBudgetTest': 26,
      'test_client_logic_budget.LogicTCPTest': 2,
      'test_client_logic_budget.LogicAsyncTCPTest': 1,
      'test_tcp_client_budget.BufferBudgetTest': 7,
      'test_tcp_client_budget.TCPClientBudgetTest': 13,
      'test_tcp_client_budget.AsyncTCPClientBudgetTest': 12,
  }
  if args.native:
    requirements['test_server_native.ServerNativeTest'] = 2
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
               if thread.name.startswith(('football-server-', 'football-tcp-', 'tcp-budget-', 'presentation-budget-'))]
  text = log.read_text(encoding='utf-8')
  markers = ('ResourceWarning:', 'Task exception was never retrieved',
             'Task was destroyed but it is pending', 'Exception in callback',
             'Exception ignored in:', 'Exception in thread', 'Cancelling an overlapped future failed',
             'was never awaited')
  observed = [marker for marker in markers if marker in text]
  sources = [
      'gfootball/frame_sync/server_state.py', 'gfootball/frame_sync/server_runtime.py',
      'gfootball/frame_sync/server_api.py', 'gfootball/frame_sync/test_server_budget.py',
      'gfootball/frame_sync/test_server_native.py',
      'gfootball/frame_sync/server.py', 'gfootball/frame_sync/server_async.py',
      'gfootball/frame_sync/__init__.py', '.project/checks/python_server_probe.py',
      'gfootball/frame_sync/client_buffers.py', 'gfootball/frame_sync/client_tcp.py',
      'gfootball/frame_sync/client.py', 'gfootball/frame_sync/client_logic.py',
      'gfootball/frame_sync/protocol.py', 'gfootball/frame_sync/config.py',
      'gfootball/frame_sync/client_async.py', 'gfootball/frame_sync/client_tcp_async.py',
      'gfootball/frame_sync/test_tcp_client_budget.py', 'gfootball/frame_sync/test_client_logic_budget.py',
      'gfootball/frame_sync/presentation.py', 'gfootball/frame_sync/presentation_state.py',
      'gfootball/frame_sync/presentation_loop.py', 'gfootball/frame_sync/test_presentation_budget.py',
  ]
  for path in sources:
    compile((ROOT / path).read_text(encoding='utf-8'), path, 'exec')
  sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
  native_passed = (args.native and groups.get('test_server_native.ServerNativeTest') == 2 and not any(
      'ServerNativeTest' in str(test) for test, _ in result.failures + result.errors + result.skipped))
  report = dict(
      scope='Real sync/async TCP servers with explicit deterministic engine oracle; client/logic/presentation regressions',
      # 2026-09-10: request/actual verified coverage are distinct evidence fields.
      # native_GameEnv_executed=False, formal_linux_acceptance=False,
      native_GameEnv_requested=args.native, native_GameEnv_executed=native_passed,
      native_GameEnv_suite_passed=native_passed, formal_linux_acceptance=False,
      passed=result.wasSuccessful() and all(groups[name] >= count for name, count in requirements.items())
      and not result.skipped and not remaining and not observed,
      tests=result.testsRun, groups=groups, skipped=len(result.skipped),
      failures=[dict(test=str(test), traceback=traceback) for test, traceback in result.failures],
      errors=[dict(test=str(test), traceback=traceback) for test, traceback in result.errors],
      observed_failure_markers=observed, remaining_owned_threads=remaining,
      log_sha256=sha(log), python=sys.version, executable=sys.executable, platform=platform.platform(),
      syntax_compiled=sources, sources={path: sha(ROOT / path) for path in sources})
  (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
  print(json.dumps(report, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
