#!/usr/bin/env python3
"""Archive NumPy ownership / actual recording I/O; optionally test the env adapter."""
import argparse
import ast
import faulthandler
import gc
import hashlib
import json
import os
import multiprocessing
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
  parser.add_argument('--environment', action='store_true',
                      help='Also import the actual native/Gym environment recording entrypoint')
  parser.add_argument('--replay', action='store_true',
                      help='Also verify streaming replay I/O, shared sources and lifecycle contracts')
  parser.add_argument('--native', action='store_true',
                      help='With --environment --replay, also run actual GameEnv record/replay identity')
  parser.add_argument('--rendering', action='store_true',
                      help='With --native, also require real SDL/OpenGL renderer ownership and rollback')
  args = parser.parse_args()
  if args.rendering and not args.native:
    parser.error('--rendering requires --native')
  if args.native and not (args.environment and args.replay):
    parser.error('--native requires --environment --replay')
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  sys.path.insert(0, str(ROOT))
  os.chdir(ROOT)
  import cv2
  import numpy
  faulthandler.enable()
  # 2026-09-09: the optional native scenario run has a separate bounded deadline.
  # faulthandler.dump_traceback_later(90, exit=True)
  faulthandler.dump_traceback_later(180 if args.native else 90, exit=True)
  warnings.simplefilter('always', ResourceWarning)
  requirements = {
      # 2026-09-10: the environment now imports the bounded resource pool.
      # 2026-09-10: also preserve the creation failure when terminal cleanup reports an error.
      # 'gfootball.test_engine_pool.EnginePoolTest': 20,
      'gfootball.test_engine_pool.EnginePoolTest': 21,
      'gfootball.test_owned_engine.OwnedEngineTest': 17,
      'gfootball.test_recording_buffers.RecordingOwnershipTest': 14,
      'gfootball.test_recording_buffers.RecordingHistoryTest': 8,
      'gfootball.test_recording_output.RecordingOutputTest': 21,
      # 2026-09-09: real independent owners/processes and directory OS leases.
      # 2026-09-09: retained failed-constructor traceback must not close reused fds.
      # 'gfootball.test_recording_directory.RecordingDirectoryTest': 17,
      'gfootball.test_recording_directory.RecordingDirectoryTest': 18,
  }
  if args.environment:
    requirements['gfootball.test_recording_environment.RecordingEnvironmentTest'] = 7
  if args.replay:
    requirements.update({
        'gfootball.test_replay_io.ReplayFilesTest': 16,
        'gfootball.test_replay_io.ReplayTimingTest': 5,
        'gfootball.test_replay_sources.ReplaySourceTest': 14,
        'gfootball.test_replay_lifecycle.ReplayLifecycleTest': 12,
    })
    if args.environment:
      requirements['gfootball.test_replay_environment.ReplayEnvironmentTest'] = 6
    if args.native:
      requirements['gfootball.test_replay_environment.ReplayGameEnvTest'] = 2
      requirements['gfootball.test_engine_pool_native.EnginePoolNativeTest'] = 6
      requirements['gfootball.test_owned_engine_native.OwnedEngineNativeTest'] = 3
      if args.rendering:
        requirements['gfootball.test_engine_pool_native.EnginePoolRenderingTest'] = 4
  suite = unittest.TestSuite()
  groups = {}
  for name in requirements:
    part = unittest.defaultTestLoader.loadTestsFromName(name)
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
  sources = [
      '.project/checks/native_runtime_identity.py',
      # 2026-09-10: environment imports now use the explicit legacy/Gymnasium boundary.
      'gfootball/__init__.py', 'gfootball/env/__init__.py',
      'gfootball/env/legacy_api.py', 'gfootball/env/wrappers.py', 'engine/__init__.py',
      # 2026-09-10: directory and observation owners share the lightweight error type.
      'gfootball/recording_errors.py',
      # 2026-09-10: track the new pool dependency and planned actual native tests.
      'gfootball/engine_pool.py', 'gfootball/test_engine_pool.py',
      'gfootball/owned_engine.py', 'gfootball/test_owned_engine.py',
      'gfootball/test_owned_engine_native.py', 'gfootball/frame_sync/server_runtime.py',
      'gfootball/frame_sync/match_identity.py',
      'gfootball/frame_sync/match_lifecycle.py',
      'gfootball/frame_sync/frame_pacing.py',
      'gfootball/frame_sync/match_cadence.py',
      'gfootball/test_engine_pool_native.py',
      # 2026-09-09: directory OS lease code is part of the current output path.
      'gfootball/recording_directory.py',
      'gfootball/test_recording_directory.py',
      'gfootball/recording_buffers.py', 'gfootball/recording_output.py',
      'gfootball/test_recording_buffers.py', 'gfootball/test_recording_output.py',
      'gfootball/env/observation_processor.py', 'gfootball/env/config.py',
      'gfootball/env/football_env_core.py', 'gfootball/env/script_helpers.py',
      'gfootball/test_recording_environment.py', '.project/checks/python_recording_probe.py',
  ]
  if args.replay:
    sources.extend([
        'gfootball/replay_io.py', 'gfootball/replay_sources.py',
        'gfootball/test_replay_io.py', 'gfootball/test_replay_sources.py',
        'gfootball/test_replay_lifecycle.py', 'gfootball/test_replay_environment.py',
        'gfootball/env/replay_support.py', 'gfootball/env/players/replay.py',
        'gfootball/env/player_base.py', 'gfootball/env/football_action_set.py',
        'gfootball/env/football_env.py', 'gfootball/env/script_helpers_test.py',
    ])
  compiled = []
  for path in sources:
    compile((ROOT / path).read_text(encoding='utf-8'), path, 'exec')
    compiled.append(path)
  # 2026-09-10: include fresh ownership and both actual native factory paths.
  # compatible = ('gfootball/engine_pool.py', 'gfootball/env/football_env_core.py')
  compatible = ('gfootball/engine_pool.py', 'gfootball/owned_engine.py',
                'gfootball/env/football_env_core.py', 'gfootball/frame_sync/server_runtime.py',
                'gfootball/frame_sync/match_identity.py')
  for path in compatible:
    ast.parse((ROOT / path).read_text(encoding='utf-8'), path, feature_version=(3, 9))
  # 2026-09-10: syntax alone cannot catch a lost public class or a duplicate
  # constructor. This is static API validation, never native execution evidence.
  core_ast = ast.parse((ROOT / 'gfootball/env/football_env_core.py').read_text(encoding='utf-8'))
  classes = {node.name: node for node in core_ast.body if isinstance(node, ast.ClassDef)}
  for class_name, signature in (('EnvState', ['self']), ('FootballEnvCore', ['self', 'config'])):
    node = classes[class_name]
    methods = [item for item in node.body if isinstance(item, ast.FunctionDef)]
    names = [item.name for item in methods]
    if len(names) != len(set(names)):
      raise RuntimeError('Duplicate methods in ' + class_name)
    constructor = next(item for item in methods if item.name == '__init__')
    if [arg.arg for arg in constructor.args.args] != signature:
      raise RuntimeError('Changed public constructor: ' + class_name)
  from gfootball.engine_pool import ENGINE_POOL
  ENGINE_POOL.clear_idle()
  pool_state = ENGINE_POOL.stats()
  text = log.read_text(encoding='utf-8')
  from gfootball.recording_directory import _lock_descriptors
  remaining_threads = [thread.name for thread in threading.enumerate()
                       if thread.name.startswith(('football-recording-directory-', 'football-engine-pool-', 'football-engine-owned-'))]
  remaining_processes = [process.name for process in multiprocessing.active_children()
                         if process.name.startswith('football-recording-directory-test-')]
  sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
  native_name = 'gfootball.test_replay_environment.ReplayGameEnvTest'
  # 2026-09-10: include the actual pool/Core suite in native success.
  # native_passed = (args.native and groups.get(native_name) == 2 and not any(
  #     native_name in str(test) for test, _ in result.failures + result.errors + result.skipped))
  native_passed = (args.native and result.wasSuccessful() and not result.skipped
                  and groups.get(native_name) == 2
                  # 2026-09-10: require direct/Core actual admission as well.
                  # and groups.get('gfootball.test_engine_pool_native.EnginePoolNativeTest') == 6)
                  and groups.get('gfootball.test_engine_pool_native.EnginePoolNativeTest') == 6
                  and groups.get('gfootball.test_owned_engine_native.OwnedEngineNativeTest') == 3)
  rendering_passed = (args.rendering and native_passed
                     and groups.get('gfootball.test_engine_pool_native.EnginePoolRenderingTest') == 4)
  report = dict(
      # 2026-09-09: output uses live OS reservations across independent processes.
      # scope='Owned NumPy observation buffers, actual pickle/files/MJPG encode-decode, targeted I/O failures',
      # scope='Owned NumPy observation buffers, actual pickle/files/MJPG, cross-process directory quotas and crash recovery',
      scope=('Bounded engine resource ownership, owned NumPy recording, actual pickle/files/MJPG, directory quotas/crash recovery'
             + (', streaming replay I/O/shared action cursors/lifecycle contracts' if args.replay else '')),
      environment_adapter_executed=args.environment,
      # 2026-09-09: distinguish requested native checks from a passed actual suite.
      # native_GameEnv_executed=False, formal_linux_acceptance=False,
      replay_checks_requested=args.replay, native_GameEnv_requested=args.native,
      native_GameEnv_suite_passed=native_passed, native_GameEnv_executed=native_passed,
      renderer_requested=args.rendering, renderer_suite_passed=rendering_passed,
      resource_oracle_is_GameEnv=False, engine_pool_final=pool_state, core_public_api_ast_checked=True,
      python39_syntax_checked=list(compatible), python39_runtime_executed=False,
      formal_linux_acceptance=False,
      passed=result.wasSuccessful() and all(groups[name] >= count for name, count in requirements.items())
      # 2026-09-09: leaked worker/lock ownership fails acceptance as well.
      # and not result.skipped and not any(marker in text for marker in ('ResourceWarning:', 'Exception ignored in:')),
      # 2026-09-10: also require every engine lease/factory to have been released.
      and not pool_state['live'] and not pool_state['leased'] and not pool_state['renderer_reserved']
      and not result.skipped and not remaining_threads and not remaining_processes and not _lock_descriptors
      and not any(marker in text for marker in ('ResourceWarning:', 'Exception ignored in:', 'Exception in thread')),
      tests=result.testsRun, groups=groups, skipped=len(result.skipped),
      remaining_owned_threads=remaining_threads, remaining_owned_processes=remaining_processes,
      remaining_owned_lock_descriptors=sorted(_lock_descriptors),
      failures=[dict(test=str(test), traceback=traceback) for test, traceback in result.failures],
      errors=[dict(test=str(test), traceback=traceback) for test, traceback in result.errors],
      log_sha256=sha(log), python=sys.version, executable=sys.executable,
      numpy=numpy.__version__, opencv=cv2.__version__, platform=platform.platform(),
      syntax_compiled=compiled, sources={path: sha(ROOT / path) for path in sources})
  if args.native:
    report['native_runtime'] = native_runtime_identity(ROOT)
  (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
  print(json.dumps(report, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
