#!/usr/bin/env python3
"""Archive bounded UDP, real socket faults, and common frame/logic contracts."""
import argparse
import ast
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
  os.chdir(ROOT)
  sys.path.insert(0, str(ROOT))
  faulthandler.enable()
  faulthandler.dump_traceback_later(60, exit=True)
  warnings.simplefilter('always', ResourceWarning)
  requirements = {
      'test_udp_budget.UDPStateTest': 18,
      'test_udp_budget.UDPTransportTest': 9,
      'test_udp_client_budget.UDPClientTest': 26,
      'test_tcp_client_budget.BufferBudgetTest': 7,
      'test_client_logic_budget.LogicBudgetTest': 26,
  }
  suite, groups = unittest.TestSuite(), {}
  for name in requirements:
    tests = unittest.defaultTestLoader.loadTestsFromName('gfootball.frame_sync.' + name)
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
  remaining = [thread.name for thread in threading.enumerate()
               if thread.name.startswith(('football-udp-', 'football-tcp-', 'tcp-budget-'))]
  text = log.read_text(encoding='utf-8')
  markers = ('ResourceWarning:', 'Exception ignored in:', 'Exception in thread',
             'Task exception was never retrieved', 'Task was destroyed but it is pending',
             'Exception in callback', 'Cancelling an overlapped future failed', 'was never awaited')
  observed = [marker for marker in markers if marker in text]
  sources = {'.project/checks/python_udp_probe.py', 'engine/src/frame_sync/reliable_udp.hpp'}
  for module in list(sys.modules.values()):
    filename = getattr(module, '__file__', None)
    if filename:
      path = Path(filename).resolve()
      if path.suffix == '.py' and path.is_relative_to(ROOT):
        sources.add(path.relative_to(ROOT).as_posix())
  for filename in sources:
    if filename.endswith('.py'):
      compile((ROOT / filename).read_text(encoding='utf-8'), filename, 'exec')
  compatible = ['gfootball/frame_sync/' + name for name in (
      'client_udp.py', 'client_udp_runtime.py', 'udp_state.py', 'udp_transport.py', 'test_e2e_udp.py')]
  for filename in compatible:
    ast.parse((ROOT / filename).read_text(encoding='utf-8'), filename, feature_version=(3, 9))
  sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
  report = dict(
      scope='Bounded ordered Python UDP, actual loopback loss/duplicates/reorder/close, shared decoder and logic reducer contracts',
      native_GameEnv_executed=False, native_UDP_server_executed=False,
      formal_linux_acceptance=False, WAN_executed=False,
      passed=result.wasSuccessful() and all(groups[name] >= count for name, count in requirements.items())
      and not result.skipped and not remaining and not observed,
      tests=result.testsRun, groups=groups, skipped=len(result.skipped),
      failures=[dict(test=str(test), traceback=traceback) for test, traceback in result.failures],
      errors=[dict(test=str(test), traceback=traceback) for test, traceback in result.errors],
      observed_failure_markers=observed, remaining_owned_threads=remaining,
      log_sha256=sha(log), python=sys.version, executable=sys.executable, platform=platform.platform(),
      python39_syntax_checked=compatible, python39_runtime_executed=False,
      syntax_compiled=sorted(name for name in sources if name.endswith('.py')),
      sources={name: sha(ROOT / name) for name in sorted(sources)})
  (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
  print(json.dumps({key: value for key, value in report.items() if key not in ('sources', 'syntax_compiled')}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
