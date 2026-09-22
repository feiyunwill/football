#!/usr/bin/env python3
"""Archive frame-replay ownership, storage and actual JSONL file checks."""
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

# 2026-09-10: record the libraries actually loaded from the installed wheel.
from native_runtime_identity import native_runtime_identity

ROOT = Path(__file__).resolve().parents[2]


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--match', action='store_true', help='Require real local match TCP/menu/save/playback integration with explicit engine oracle')
  # 2026-09-10: require the v5 cadence contract and both transport confirmation paths.
  # parser.add_argument('--multiplayer', action='store_true', help='With --match, require actual v4 host/join/recovery/end/preferences integration')
  # 2026-09-10: v6 adds control epochs to the match contract.
  # parser.add_argument('--multiplayer', action='store_true', help='With --match, require v5 cadence, host/join/recovery/end/preferences integration')
  # 2026-09-13: require the supported v7 product match contract.
  # parser.add_argument('--multiplayer', action='store_true', help='With --match, require v6 cadence/control, host/join/recovery/end/preferences integration')
  parser.add_argument('--multiplayer', action='store_true', help='With --match, require v7 cadence/control, host/join/recovery/end/preferences integration')
  # 2026-09-10: UDP now carries the same v5 application handshake.
  # parser.add_argument('--udp-multiplayer', action='store_true', help='With --match --multiplayer, require actual UDP v4 matches and fault/recovery cases')
  # parser.add_argument('--udp-multiplayer', action='store_true', help='With --match --multiplayer, require actual UDP v5 matches and fault/recovery cases')
  # 2026-09-13: require the supported v7 product match contract.
  # parser.add_argument('--udp-multiplayer', action='store_true', help='With --match --multiplayer, require v6 UDP matches plus TCP/UDP pause and fault/recovery cases')
  parser.add_argument('--udp-multiplayer', action='store_true', help='With --match --multiplayer, require v7 UDP matches plus TCP/UDP pause and fault/recovery cases')
  parser.add_argument('--graphics', action='store_true', help='Require graphical input/owner/socket/menu integration; --native also requires actual SDL/OpenGL')
  parser.add_argument('--native', action='store_true', help='Also require actual GameEnv match continuation and replay; needs --match')
  args = parser.parse_args()
  if args.multiplayer and not args.match:
    parser.error('--multiplayer requires --match')
  if args.udp_multiplayer and not args.multiplayer:
    parser.error('--udp-multiplayer requires --multiplayer --match')
  if args.native and not args.match:
    parser.error('--native requires --match')
  if args.graphics and not (args.match and args.multiplayer and args.udp_multiplayer):
    parser.error('--graphics requires --match --multiplayer --udp-multiplayer')
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  os.chdir(ROOT)
  sys.path.insert(0, str(ROOT))
  faulthandler.enable()
  # 2026-09-10: native graphics builds multiple identified engines; still bounded.
  # faulthandler.dump_traceback_later(120, exit=True)
  # 2026-09-10: additional actual pause/recovery fault cases have bounded waits.
  # faulthandler.dump_traceback_later(600 if args.native and args.graphics else 120, exit=True)
  faulthandler.dump_traceback_later(600 if args.native and args.graphics else (180 if args.udp_multiplayer else 120), exit=True)
  warnings.simplefilter('always', ResourceWarning)
  requirements = {
      'test_replay_records.ReplayRecordTest': 10,
      'test_replay_store.ReplayStoreTest': 16,
      'test_replay_files.ReplayFileTest': 16,
      'save_test': 15,
      'phase7_integration_test': 7,
  }
  if args.match:
    # 2026-09-10: finalized recorder close must also release its retained budget.
    # requirements.update({'test_match_archive.MatchIntegrationTest': 20,
    requirements.update({'test_match_archive.MatchIntegrationTest': 21,
                         'test_owned_match.OwnedMatchTest': 5,
                         # 2026-09-10: explicit finish and primary-failure cleanup.
                         # 'test_match_lifecycle.MatchLifecycleTest': 17,
                         # 'test_match_lifecycle.MatchCompletionIntegrationTest': 5,
                         'test_match_lifecycle.MatchLifecycleTest': 18,
                         # 2026-09-10: require both public server loops too.
                         # 'test_match_lifecycle.MatchCompletionIntegrationTest': 7,
                         'test_match_lifecycle.MatchCompletionIntegrationTest': 9,
                         'test_save_budget.SaveBudgetTest': 14,
                         'test_save_budget.ProgressBudgetTest': 6,
                         'test_save_budget.SaveDiskTest': 15})
    requirements.update({'test_match_identity.MatchIdentityTest': 9,
                         # 2026-09-10: verify explicit-font fallback selection.
                         # 'test_match_identity.FingerprintFilesTest': 9,
                         'test_match_identity.FingerprintFilesTest': 10,
                         'test_match_identity.NativeMappingParserTest': 4})
  if args.native:
    # 2026-09-10: native acceptance must also identify the actual loaded core.
    # requirements['test_match_native.MatchNativeTest'] = 1
    # 2026-09-10: require actual mutable native scenario team construction.
    # requirements['test_match_native.MatchNativeTest'] = 2
    requirements['test_match_native.MatchNativeTest'] = 3
    requirements['test_match_completion_native.MatchCompletionNativeTest'] = 3
  if args.match:
    # 2026-09-10: local authority and commands must pass even without graphics.
    requirements.update({'test_match_pause_ui.PauseCommandTest': 6,
                         # 2026-09-10: verify and consume local wire hashes, including delayed/invalid records.
                         # 'test_match_pause_ui.LocalPauseTest': 10})
                         'test_match_pause_ui.LocalPauseTest': 13})
    requirements.update({'test_frame_pacing.FramePacingTest': 11,
                         'test_frame_pacing.AsyncFramePacingTest': 2,
                         'test_pacing_runtime.PacingRuntimeTest': 6})
  if args.multiplayer:
    # 2026-09-10: v6 primitives remain opt-in; v5 socket matches still execute.
    # 2026-09-10: production matches now initialize and execute the v6 controls.
    requirements.update({'test_match_control.MatchControlCodecTest': 9,
                         # 2026-09-10: also verify actual holder rewind and idle serialization.
                         # 'test_match_control.MatchControlLogicTest': 18,
                         'test_match_control.MatchControlLogicTest': 19,
                         'test_match_control.MatchControlInputTest': 7})
    # 2026-09-13: v7 adds explicit time conversion, legacy rejection and replay cadence.
    # requirements.update({'test_match_cadence.MatchCadenceTest': 6,
    #                      'test_match_cadence.MatchCadenceNetworkTest': 7})
    requirements.update({'test_match_cadence.MatchCadenceTest': 6,
                         'test_match_cadence.MatchCadenceNetworkTest': 7,
                         'test_product_cadence.ProductCadenceTest': 8})
    if args.native:
      requirements['test_product_cadence.ProductCadenceNativeTest'] = 2
    # 2026-09-10: duplicates remain idempotent after the authority cursor advances.
    # requirements['test_match_pause_network.MatchControlBufferTest'] = 5
    requirements['test_match_pause_network.MatchControlBufferTest'] = 6
    requirements.update({'test_multiplayer.MatchBootstrapTest': 8,
                         # 2026-09-10: public server loops and persisted continuation defaults.
                         # 'test_multiplayer.MultiplayerTest': 19,
                         # 'test_menu_options.MenuOptionsTest': 8})
                         'test_multiplayer.MultiplayerTest': 21,
                         'test_menu_options.MenuOptionsTest': 9})
    if args.native:
      requirements['test_multiplayer_native.NativeMultiplayerTest'] = 1
  if args.udp_multiplayer:
    # 2026-09-10: terminal End supersedes an unconsumed pause confirmation timer.
    # requirements['test_match_pause_network.MatchPauseNetworkTest'] = 15
    requirements['test_match_pause_network.MatchPauseNetworkTest'] = 16
    requirements['test_multiplayer_udp.MultiplayerUDPTest'] = 15
    if args.native:
      requirements['test_multiplayer_udp_native.NativeMultiplayerUDPTest'] = 1
  if args.graphics:
    requirements['test_render_interpolation.RenderInterpolationTest'] = 14
    # 2026-09-10: actual UI owner to Local/Host/Join pause and persistent feedback.
    requirements['test_match_pause_ui.GraphicalPauseTest'] = 6
    requirements.update({'test_graphical_input.GraphicalInputTest': 9,
                         # 2026-09-10: include actual menu routing and immutable display role.
                         # 'test_graphical_runtime.GraphicalRuntimeTest': 12})
                         'test_graphical_runtime.GraphicalRuntimeTest': 14})
    if args.native:
      # 2026-09-10: require actual intermediate images and unchanged canonical physics.
      # requirements['test_graphical_native.GraphicalNativeTest'] = 3
      # 2026-09-10: require real local pause and persistent in-game HUD pixels.
      # requirements['test_graphical_native.GraphicalNativeTest'] = 4
      requirements['test_graphical_native.GraphicalNativeTest'] = 5
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
  from gfootball.recording_directory import _lock_descriptors
  # 2026-09-10: actual match tests also own real TCP/server workers.
  # remaining = [thread.name for thread in threading.enumerate() if thread.name.startswith('frame-replay-')]
  # 2026-09-10: multiplayer owns reconnect and explicit test-player workers too.
  # remaining = [thread.name for thread in threading.enumerate() if thread.name.startswith(
  #     ('frame-replay-', 'football-tcp-', 'football-server-', 'football-save-'))]
  remaining = [thread.name for thread in threading.enumerate() if thread.name.startswith(('frame-replay-', 'football-'))]
  active_processes = [process.pid for process in (getattr(subprocess, '_active', None) or []) if process.poll() is None]
  text = log.read_text(encoding='utf-8')
  markers = ('ResourceWarning:', 'Exception ignored in:', 'Exception in thread',
             'Task exception was never retrieved', 'Task was destroyed but it is pending')
  observed = [marker for marker in markers if marker in text]
  # Capture actual local imported dependencies, including original helper tests
  # and the existing atomic output/directory implementation they exercised.
  sources = {'.project/checks/frame_replay_probe.py'}
  sources.add('.project/checks/native_runtime_identity.py')
  # 2026-09-10: installed native loaders are outside ROOT but still affect this run.
  if args.native:
    sources.add('engine/__init__.py')
  if args.match:
    sources.add('gfootball/frame_sync/test_match_native.py')
    sources.add('gfootball/frame_sync/test_match_completion_native.py')
  if args.multiplayer:
    sources.add('gfootball/frame_sync/test_multiplayer_native.py')
  if args.udp_multiplayer:
    sources.add('gfootball/frame_sync/test_multiplayer_udp_native.py')
  if args.graphics:
    sources.add('gfootball/frame_sync/test_graphical_native.py')
    # 2026-09-10: compile the added probe before reporting Python syntax coverage.
    sources.add('.project/checks/render_pose_contract.py')
  for module in list(sys.modules.values()):
    filename = getattr(module, '__file__', None)
    if filename:
      path = Path(filename).resolve()
      if path.suffix == '.py' and path.is_relative_to(ROOT):
        sources.add(path.relative_to(ROOT).as_posix())
  for filename in sources:
    compile((ROOT / filename).read_text(encoding='utf-8'), filename, 'exec')
  compatible = ['gfootball/frame_sync/' + name for name in (
      'replay.py', 'replay_data.py', 'replay_store.py', 'replay_file.py')]
  if args.match:
    # 2026-09-10: include the build/content compatibility implementation.
    # compatible += ['gfootball/frame_sync/' + name + '.py' for name in ('match_archive', 'local_runtime', 'local_play', 'main_menu')]
    compatible += ['gfootball/frame_sync/' + name + '.py' for name in (
        # 2026-09-10: include the rollbackable completion policy.
        # 'match_archive', 'match_identity', 'local_runtime', 'local_play', 'main_menu')]
        'match_archive', 'match_identity', 'match_lifecycle', 'local_runtime', 'local_play', 'main_menu')]
    compatible += ['gfootball/engine_pool.py', 'gfootball/owned_engine.py']
  if args.multiplayer:
    compatible += ['gfootball/frame_sync/' + name + '.py' for name in (
        'match_control', 'test_match_control',
        'test_match_pause_network',
        # 2026-09-13: include the new contract in Python 3.9 syntax compatibility checks.
        # 'match_cadence', 'test_match_cadence',
        'match_cadence', 'test_match_cadence', 'test_product_cadence',
        'match_bootstrap', 'multiplayer_transport', 'multiplayer_runtime', 'menu_options',
        'client_tcp', 'client_reconnect', 'client_logic', 'server_runtime', 'server_state', 'protocol')]
  if args.udp_multiplayer:
    compatible += ['gfootball/frame_sync/' + name + '.py' for name in (
        'multiplayer_udp', 'client_udp_resume', 'client_udp_runtime', 'server_udp')]
  if args.graphics:
    compatible += ['gfootball/frame_sync/' + name + '.py' for name in (
        'presentation_loop', 'presentation_state', 'test_render_interpolation',
        'graphical_input', 'graphical_runtime', 'test_graphical_input', 'test_graphical_runtime', 'test_graphical_native')]
  if args.match:
    compatible += ['gfootball/frame_sync/' + name + '.py' for name in (
        # 2026-09-10: parse the required owner/UI regression module as Python 3.9 syntax.
        # 'frame_pacing', 'test_frame_pacing', 'test_pacing_runtime')]
        'frame_pacing', 'test_frame_pacing', 'test_pacing_runtime', 'test_match_pause_ui')]
  for filename in compatible:
    ast.parse((ROOT / filename).read_text(encoding='utf-8'), filename, feature_version=(3, 9))
  if args.graphics:
    sources.update(('engine/ai.cpp', 'engine/src/frame_sync/python_window_input.hpp'))
    # 2026-09-10: include native card fixtures/build inputs as source fingerprints;
    # the portable suite does not execute or compile the native contract.
    sources.update(('engine/src/onthepitch/referee.hpp', 'engine/CMakeLists.txt',
                    'engine/sources.cmake', 'engine/tests/engine_render_pose_contract.cpp',
                    '.project/checks/render_pose_contract.py'))
    # 2026-09-10: retain fingerprints of all changed native rendering implementations.
    for stem in ('game_env', 'gametask', 'onthepitch/ball', 'onthepitch/match', 'onthepitch/team',
                 'onthepitch/officials', 'onthepitch/player/playerbase',
                 'onthepitch/player/humanoid/humanoidbase'):
      sources.update('engine/src/' + stem + extension for extension in ('.cpp', '.hpp'))
  sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
  report = dict(
      # 2026-09-10: distinguish the actual local loop/oracle from native execution.
      # scope='Immutable match frame/event records, bounded collections, real streaming JSONL files and original Python product helper regressions',
      # native_GameEnv_executed=False, rendered_match_executed=False, formal_linux_acceptance=False,
      scope='Bounded replay records/files and helper regressions' +
            ('; actual local TCP match, persistent continuation, menu and verified playback; save regressions' if args.match else ''),
      match_integration_requested=args.match, native_GameEnv_requested=args.native,
      multiplayer_integration_requested=args.multiplayer,
      udp_multiplayer_integration_requested=args.udp_multiplayer,
      udp_multiplayer_measurements=(sys.modules['gfootball.frame_sync.test_multiplayer_udp'].MEASUREMENTS if args.udp_multiplayer else {}),
      native_GameEnv_executed=bool(args.native and result.wasSuccessful() and not result.skipped),
      # 2026-09-10: only required real SDL checks can establish rendered execution.
      # rendered_match_executed=False, formal_linux_acceptance=False,
      graphics_requested=args.graphics,
      rendered_match_executed=bool(args.graphics and args.native and result.wasSuccessful() and not result.skipped),
      formal_linux_acceptance=False,
      passed=result.wasSuccessful() and all(groups[name] >= count for name, count in requirements.items())
      and not result.skipped and not remaining and not active_processes and not _lock_descriptors and not observed,
      tests=result.testsRun, groups=groups, skipped=len(result.skipped),
      failures=[dict(test=str(test), traceback=traceback) for test, traceback in result.failures],
      errors=[dict(test=str(test), traceback=traceback) for test, traceback in result.errors],
      observed_failure_markers=observed, remaining_owned_threads=remaining,
      remaining_tracked_subprocesses=active_processes, remaining_owned_lock_descriptors=sorted(_lock_descriptors),
      log_sha256=sha(log), python=sys.version, executable=sys.executable, platform=platform.platform(),
      python39_syntax_checked=compatible, python39_runtime_executed=False,
      numpy=sys.modules['numpy'].__version__, opencv=sys.modules['cv2'].__version__,
      # 2026-09-10: C++ fingerprints are not Python compilation evidence.
      # syntax_compiled=sorted(sources), sources=
      syntax_compiled=sorted(name for name in sources if name.endswith('.py')), sources={name: sha(ROOT / name) for name in sorted(sources)})
  if args.native:
    report['native_runtime'] = native_runtime_identity(ROOT)
  (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
  print(json.dumps({key: value for key, value in report.items() if key not in ('sources', 'syntax_compiled')}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
