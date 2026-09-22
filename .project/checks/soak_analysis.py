"""Long-match result validator with fixed raw-sample and trajectory checks.

Keep the original five acceptance thresholds and every sample. This module
evaluates raw measurements; callers must separately validate the process exit,
actual executable identity, detector configuration and source freshness.
"""
import statistics

import match_benchmark as benchmark
from native_boundary import require

WARMUP = 1000
SAMPLES = 36000
WINDOW = 6000
P99_BUDGET_NS = 50_000_000
RSS_GROWTH_BYTES = 4 * 1024 * 1024
RSS_PLATEAU_BYTES = 256 * 1024
TRAJECTORY_FIELDS = ('input_hash', 'warm_hash', 'final_hash', 'state_checkpoints', 'active_flags')


def assess(result, seed, cpu, *, reference=None):
    """Recompute all summaries and windows before applying the fixed contract."""
    assertions = benchmark.validate_run(result, seed, WARMUP, SAMPLES, cpu)
    assertions += result['assertions']
    if reference is not None:
        assertions += benchmark.validate_run(reference, seed, WARMUP, SAMPLES, reference['cpu'])
        for field in TRAJECTORY_FIELDS:
            require(result[field] == reference[field], f'Long-match trajectory changed: {field}')
            assertions += 1
    windows = [benchmark.distribution(result['raw_frame_ns'][start:start + WINDOW])
               for start in range(0, SAMPLES, WINDOW)]
    observations = result['rss_checkpoints_bytes']
    window_medians = [statistics.median(observations[start // 100 + 1:(start + WINDOW) // 100 + 1])
                      for start in range(0, SAMPLES, WINDOW)]
    quarter = len(observations) // 4
    rss = dict(warm=result['warm_rss_bytes'], observed_max=max(observations),
               final=result['final_rss_bytes'], closed=result['closed_rss_bytes'],
               process_peak_including_replay=result['peak_rss_bytes'],
               first_quarter_median=statistics.median(observations[:quarter]),
               last_quarter_median=statistics.median(observations[-quarter:]),
               window_medians=window_medians)
    requirements = dict(
        steady_p99=result['steady']['p99_ns'] < P99_BUDGET_NS,
        every_window_p99=all(window['p99_ns'] < P99_BUDGET_NS for window in windows),
        rss_growth=max(observations) <= result['warm_rss_bytes'] + RSS_GROWTH_BYTES,
        rss_quarter_drift=rss['last_quarter_median'] <= rss['first_quarter_median'] + RSS_PLATEAU_BYTES,
        rss_late_plateau=max(window_medians[-3:]) - min(window_medians[-3:]) <= RSS_PLATEAU_BYTES,
    )
    assertions += len(requirements)
    failures = [name for name, passed in requirements.items() if not passed]
    return dict(passed=not failures, assertions=assertions, skipped=0, seed=seed, cpu=cpu,
                requirements=requirements, failures=failures,
                trajectory_compared=reference is not None,
                measured_frames=SAMPLES, simulated_seconds=SAMPLES / 10,
                measured_loop_wall_seconds=result['loop_wall_ns'] / 1e9,
                steady=result['steady'], active_frames=sum(result['active_flags']),
                final_hash=result['final_hash'], frame_windows=windows, rss=rss,
                scope='native headless logical steps and observed process RSS; '
                      'simulated duration is distinct from wall-clock duration; '
                      'does not establish renderer, network or input-device latency')
