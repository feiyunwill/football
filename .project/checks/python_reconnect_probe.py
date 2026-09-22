#!/usr/bin/env python3
"""Archive automatic recovery and all affected TCP/server/logic/UDP regressions."""
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

# 2026-09-10: record the libraries actually loaded from the installed wheel.
from native_runtime_identity import native_runtime_identity

ROOT = Path(__file__).resolve().parents[2]


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--native', action='store_true', help='Also require actual GameEnv server and automatic recovery checks')
  parser.add_argument('--udp-resume', action='store_true', help='Also require cookie/epoch UDP server, loss and recovery checks')
  args = parser.parse_args()
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  os.chdir(ROOT)
  sys.path.insert(0, str(ROOT))
  faulthandler.enable()
  faulthandler.dump_traceback_later(180 if args.native else 90, exit=True)
  warnings.simplefilter('always', ResourceWarning)
  requirements = {
      'test_reconnect_budget.ResumeBufferTest': 7,
      # 2026-09-10: expired deadlines prohibit new connection establishment.
      # 'test_reconnect_budget.ResumeTransportTest': 3,
      'test_reconnect_budget.ResumeTransportTest': 4,
      # 2026-09-10: also verify actual legacy host-token binding.
      # 'test_reconnect_budget.ReconnectClientTest': 14,
      # 2026-09-10: an expired pending snapshot must not mutate the engine.
      # 'test_reconnect_budget.ReconnectClientTest': 15,
      'test_reconnect_budget.ReconnectClientTest': 16,
      'test_server_budget.ServerStateTest': 9,
      'test_server_budget.SyncServerTest': 16,
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
      'test_udp_budget.UDPStateTest': 18,
      'test_udp_budget.UDPTransportTest': 9,
      'test_udp_client_budget.UDPClientTest': 26,
  }
  if args.udp_resume:
    requirements['test_udp_resume_budget.CookieTest'] = 5
    requirements['test_udp_resume_budget.UDPResumeTest'] = 13
  if args.native:
    requirements['test_reconnect_native.ReconnectNativeTest'] = 1
    requirements['test_server_native.ServerNativeTest'] = 2
    if args.udp_resume:
      requirements['test_udp_resume_native.UDPResumeNativeTest'] = 1
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
  remaining = [thread.name for thread in threading.enumerate() if thread.name.startswith(
      ('football-reconnect-', 'football-udp-', 'football-tcp-', 'football-server-', 'tcp-budget-', 'presentation-budget-'))]
  text = log.read_text(encoding='utf-8')
  markers = ('ResourceWarning:', 'Exception ignored in:', 'Exception in thread',
             'Task exception was never retrieved', 'Task was destroyed but it is pending',
             'Exception in callback', 'Cancelling an overlapped future failed', 'was never awaited')
  observed = [marker for marker in markers if marker in text]
  # 2026-09-10: include the identity collector and actual native loader.
  # sources = {'.project/checks/python_reconnect_probe.py', 'engine/src/frame_sync/reliable_udp.hpp',
  sources = {'.project/checks/native_runtime_identity.py', 'engine/__init__.py',
             '.project/checks/python_reconnect_probe.py', 'engine/src/frame_sync/reliable_udp.hpp',
             'gfootball/frame_sync/test_reconnect_native.py', 'gfootball/frame_sync/test_server_native.py'}
  if args.udp_resume:
    sources.add('gfootball/frame_sync/test_udp_resume_native.py')
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
      'client.py', 'client_tcp.py', 'client_logic.py', 'client_reconnect.py', 'resume_protocol.py', 'server_runtime.py')]
  if args.udp_resume:
    compatible += ['gfootball/frame_sync/' + name + '.py' for name in (
        'udp_session', 'udp_state', 'udp_transport', 'client_udp_resume', 'server_udp', 'server_api')]
  for filename in compatible:
    ast.parse((ROOT / filename).read_text(encoding='utf-8'), filename, feature_version=(3, 9))
  sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
  # 2026-09-10: failed native imports must not count as execution success.
  # native_passed = args.native and not any('NativeTest' in str(test) for test, _ in result.failures + result.errors + result.skipped)
  native_passed = (args.native and result.wasSuccessful() and not result.skipped
                  and groups.get('test_reconnect_native.ReconnectNativeTest') == 1
                  and groups.get('test_server_native.ServerNativeTest') == 2)
  # 2026-09-10: include optional UDP execution separately from native C++/GameEnv.
  # report = dict(scope='Automatic Python TCP token/snapshot/handback recovery, affected TCP/server/logic/presentation/UDP regressions',
  udp_measurements = {}
  if args.udp_resume:
    from gfootball.frame_sync.test_udp_resume_budget import MEASUREMENTS
    udp_measurements = dict(MEASUREMENTS)
  report = dict(scope='Automatic Python TCP recovery and affected regressions' +
                ('; cookie/epoch UDP server, snapshot fragmentation and automatic recovery' if args.udp_resume else ''),
      native_GameEnv_requested=args.native, native_GameEnv_suite_passed=native_passed,
      native_UDP_server_executed=False, native_CPP_TCP_server_executed=False,
      python_UDP_server_executed=args.udp_resume, udp_measurements=udp_measurements,
      actual_GameEnv_over_python_UDP_passed=bool(args.udp_resume and native_passed),
      formal_linux_acceptance=False, WAN_executed=False,
      passed=result.wasSuccessful() and all(groups[name] >= count for name, count in requirements.items())
      and not result.skipped and not remaining and not observed,
      tests=result.testsRun, groups=groups, skipped=len(result.skipped),
      failures=[dict(test=str(test), traceback=traceback) for test, traceback in result.failures],
      errors=[dict(test=str(test), traceback=traceback) for test, traceback in result.errors],
      observed_failure_markers=observed, remaining_owned_threads=remaining,
      log_sha256=sha(log), python=sys.version, executable=sys.executable, platform=platform.platform(),
      python39_syntax_checked=compatible, python39_runtime_executed=False,
      sources={name: sha(ROOT / name) for name in sorted(sources)})
  if args.native:
    report['native_runtime'] = native_runtime_identity(ROOT)
  (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
  print(json.dumps({key: value for key, value in report.items() if key != 'sources'}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
