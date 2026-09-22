#!/usr/bin/env python3
"""Observe real Windows/Linux clock scheduling, separately from native gameplay."""
import argparse
import faulthandler
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]


def distribution(values):
  values = sorted(values)
  return dict(count=len(values), mean_ms=sum(values) / len(values) / 1e6,
              p95_ms=values[math.ceil(len(values) * .95) - 1] / 1e6,
              max_ms=values[-1] / 1e6)


def observe(rate, count, absolute):
  from gfootball.frame_sync.frame_pacing import FramePacer
  period = round(1e9 / rate)
  pacer = FramePacer(rate) if absolute else None
  starts = []
  began, cpu = time.monotonic_ns(), time.process_time_ns()
  for index in range(count):
    if pacer is not None:
      pacer.wait_next()
    start = time.monotonic_ns()
    starts.append(start)
    # Controlled work and one stall, not football physics or rendering.
    time.sleep(3 / rate if index == count // 2 else .003)
    if pacer is None:
      # Preserved reference algorithm from the previous production run loops.
      time.sleep(max(0., 1 / rate - (time.monotonic_ns() - start) / 1e9))
  cpu = time.process_time_ns() - cpu
  elapsed = time.monotonic_ns() - began
  return dict(algorithm='absolute' if absolute else 'previous_relative', rate_hz=rate,
      samples=count, start_offsets_ms=[(value - starts[0]) / 1e6 for value in starts],
      spacing_error=distribution([abs(b - a - period) for a, b in zip(starts, starts[1:])]),
      pre_stall_grid_drift_ms=(starts[count // 2] - starts[0] - (count // 2) * period) / 1e6,
      wall_ms=elapsed / 1e6, process_cpu_ms=cpu / 1e6,
      pacing=None if pacer is None else pacer.stats())


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  target = args.output.resolve()
  target.mkdir(parents=True, exist_ok=False)
  sys.path.insert(0, str(ROOT))
  faulthandler.enable()
  faulthandler.dump_traceback_later(90, exit=True)
  try:
    # Alternate order; still a single-host observation, not a causal benchmark.
    runs = [observe(10, 30, False), observe(10, 30, True),
            observe(60, 120, True), observe(60, 120, False)]
  finally:
    faulthandler.cancel_dump_traceback_later()
  sources = ('.project/checks/frame_pacing_probe.py', 'gfootball/frame_sync/frame_pacing.py')
  report = dict(scope='Real monotonic waits with controlled synthetic work/stall; no game engine',
      native_GameEnv_executed=False, SDL_or_GPU_executed=False, input_to_photon_measured=False,
      whole_process_rss_measured=False, formal_linux_acceptance=False,
      measurements=runs, platform=platform.platform(), python=sys.version, executable=sys.executable,
      remaining_owned_threads=[t.name for t in threading.enumerate() if t.name.startswith('football-')],
      sources={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
      acceptance_threshold_applied=False,
      limitations=['One host and one run per algorithm/rate; scheduling load and power policy are uncontrolled.',
                   'The intentional stall contributes to spacing p95/max; missed scheduling slots are not skipped simulation frames.',
                   'Sample count is insufficient for long-run p99 or input/render/network product acceptance.'])
  (target / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
  print(json.dumps({key: value for key, value in report.items() if key != 'measurements'}, indent=2))
  for row in runs:
    print(json.dumps({key: value for key, value in row.items() if key != 'start_offsets_ms'}))


if __name__ == '__main__':
  main()
