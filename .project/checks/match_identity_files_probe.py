#!/usr/bin/env python3
"""Measure the real repository content fingerprint without importing GameEnv."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import tracemalloc
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  sys.path.insert(0, str(ROOT))
  from gfootball.frame_sync import match_identity
  original = match_identity.os.read
  measurements = {}
  for name, files, trees in (
      ('resources', [('font', ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf')],
       [('data', ROOT / 'engine/data', False)]),
      ('python_policy', [('policy/server.py', ROOT / 'gfootball/frame_sync/server.py'),
                         ('policy/server_runtime.py', ROOT / 'gfootball/frame_sync/server_runtime.py'),
                         ('policy/engine_pool.py', ROOT / 'gfootball/engine_pool.py'),
                         ('policy/owned_engine.py', ROOT / 'gfootball/owned_engine.py'),
                          ('policy/match_lifecycle.py', ROOT / 'gfootball/frame_sync/match_lifecycle.py'),
                          ('policy/match_cadence.py', ROOT / 'gfootball/frame_sync/match_cadence.py'),
                         ('policy/match_identity.py', ROOT / 'gfootball/frame_sync/match_identity.py')],
       [('env', ROOT / 'gfootball/env', True), ('scenarios', ROOT / 'gfootball/scenarios', True)])):
    counts = dict(read_calls=0, read_bytes=0, max_requested_bytes=0)
    def read(descriptor, size):
      chunk = original(descriptor, size)
      counts['read_calls'] += 1
      counts['read_bytes'] += len(chunk)
      counts['max_requested_bytes'] = max(counts['max_requested_bytes'], size)
      return chunk
    tracemalloc.start()
    started = time.perf_counter()
    try:
      with mock.patch.object(match_identity.os, 'read', read):
        # 2026-09-10: match GameEnv's explicit-font resource selection.
        # digest = match_identity.fingerprint(files, trees)
        digest = match_identity.fingerprint(files, trees,
            excluded=(match_identity.UNUSED_FONT_FALLBACK,) if name == 'resources' else ())
      elapsed = time.perf_counter() - started
      current, peak = tracemalloc.get_traced_memory()
    finally:
      tracemalloc.stop()
    measurements[name] = dict(sha256=digest, seconds=elapsed,
        python_current_bytes=current, python_peak_bytes=peak, **counts)
  # 2026-09-10: these native-policy inputs are hashed without importing them;
  # track their code separately so later owner/pool changes stale this report.
  # sources = {'.project/checks/match_identity_files_probe.py'}
  sources = {'.project/checks/match_identity_files_probe.py',
             # 2026-09-10: this new native-policy file is also not imported here.
             # 'gfootball/engine_pool.py', 'gfootball/owned_engine.py'}
             'gfootball/engine_pool.py', 'gfootball/owned_engine.py', 'gfootball/frame_sync/match_lifecycle.py'}
  for module in list(sys.modules.values()):
    filename = getattr(module, '__file__', None)
    if filename:
      path = Path(filename).resolve()
      if path.suffix == '.py' and path.is_relative_to(ROOT):
        sources.add(path.relative_to(ROOT).as_posix())
  report = dict(scope='Actual repository resource and Python policy files; excludes native binaries',
      native_GameEnv_executed=False, native_library_mapping_executed=False,
      python_allocation_only=True, whole_process_rss_measured=False, formal_linux_acceptance=False,
      passed=all(0 < row['max_requested_bytes'] <= 65536 and row['read_bytes'] > 0
                 for row in measurements.values()) and 'gfootball_engine' not in sys.modules,
      platform=platform.platform(), python=sys.version, executable=sys.executable,
      measurements=measurements,
      sources={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(sources)})
  (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
  print(json.dumps(report, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
