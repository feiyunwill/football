"""Prepared oracle tests using retained original measurements, including failures."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

# 2026-09-13: canonical test location after staged native preflight.
# ROOT = Path(__file__).resolve().parents[4]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.project/checks'))
import match_benchmark as benchmark
from soak_analysis import assess, P99_BUDGET_NS


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_stage(name, expected):
    directory = ROOT / '.project/optimization/benchmarks' / name / 'evidence'
    path = directory / 'report.json'
    if sha(path) != expected:
        raise RuntimeError('Retained historical report changed')
    report = json.loads(path.read_text())
    runs = {}
    for row in report['runs']:
        path = directory / row['log']
        if row['returncode'] != 0 or sha(path) != row['log_sha256']:
            raise RuntimeError('Retained historical raw measurement changed')
        values = [json.loads(line) for line in path.read_text().splitlines() if line.startswith('{')]
        if len(values) != 1:
            raise RuntimeError('Ambiguous historical native result')
        runs[row['seed']] = values[0]
    if set(runs) != {42, 43}:
        raise RuntimeError('Missing retained seed')
    return report, runs


class SoakAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.failed_report, cls.failed = load_stage(
            'native-soak-20260910-a',
            '0c49ddcb78c44208a2d5ea488d2fea7deee920ea890509706cd847b899f56f90')
        cls.control_report, cls.control = load_stage(
            'native-soak-prefault-20260910-a',
            '686a431bd8766725e1ea44efc75d2f121ed75923a9aa80a731a5a71f6356777b')

    def sample(self):
        return copy.deepcopy(self.control[42])

    def evaluate(self, value):
        return assess(value, 42, value['cpu'])

    def summarize(self, value):
        raw, flags = value['raw_frame_ns'], value['active_flags']
        value['steady'] = benchmark.distribution(raw)
        value['active'] = benchmark.distribution([x for x, active in zip(raw, flags) if active])
        value['stopped'] = benchmark.distribution([x for x, active in zip(raw, flags) if not active])
        value['loop_wall_ns'] = max(value['loop_wall_ns'], sum(raw) + value['diagnostics_ns'])

    def test_original_failures_remain_failed_with_exact_requirements(self):
        for row in self.failed_report['runs']:
            with self.subTest(seed=row['seed']):
                result = assess(self.failed[row['seed']], row['seed'], self.failed[row['seed']]['cpu'])
                self.assertFalse(result['passed'])
                self.assertEqual(result['requirements'], row['requirements'])
                self.assertEqual(result['failures'], ['rss_quarter_drift', 'rss_late_plateau'])

    def test_prefault_control_keeps_thresholds_and_complete_trajectory(self):
        for row in self.control_report['runs']:
            with self.subTest(seed=row['seed']):
                raw = self.control[row['seed']]
                result = assess(raw, row['seed'], raw['cpu'], reference=self.failed[row['seed']])
                self.assertTrue(result['passed'])
                self.assertEqual(result['requirements'], row['requirements'])
                self.assertEqual(result['frame_windows'], row['frame_windows'])
                self.assertEqual(result['rss'], row['rss'])
                self.assertTrue(result['trajectory_compared'])

    def test_slow_window_cannot_hide_behind_global_p99(self):
        value = self.sample()
        value['raw_frame_ns'][6000:6061] = [P99_BUDGET_NS] * 61
        self.summarize(value)
        result = self.evaluate(value)
        self.assertTrue(result['requirements']['steady_p99'])
        self.assertFalse(result['requirements']['every_window_p99'])

    def test_exact_frame_budget_is_not_a_pass(self):
        value = self.sample()
        value['raw_frame_ns'][:361] = [P99_BUDGET_NS] * 361
        self.summarize(value)
        self.assertFalse(self.evaluate(value)['requirements']['steady_p99'])

    def test_forged_summary_is_rejected(self):
        value = self.sample()
        value['steady']['p99_ns'] = 1
        with self.assertRaisesRegex(RuntimeError, 'Summary differs'):
            self.evaluate(value)

    def test_missing_frame_is_rejected(self):
        value = self.sample()
        value['raw_frame_ns'].pop()
        with self.assertRaisesRegex(RuntimeError, 'Invalid raw samples'):
            self.evaluate(value)

    def test_missing_rss_checkpoint_is_rejected(self):
        value = self.sample()
        value['rss_checkpoints_bytes'].pop()
        with self.assertRaisesRegex(RuntimeError, 'Missing RSS checkpoints'):
            self.evaluate(value)

    def test_changed_interior_state_checkpoint_is_rejected(self):
        value = self.sample()
        value['state_checkpoints'][17] = '0' * 16
        with self.assertRaisesRegex(RuntimeError, 'trajectory changed: state_checkpoints'):
            assess(value, 42, value['cpu'], reference=self.failed[42])

    def test_rss_peak_is_evaluated_even_when_medians_are_flat(self):
        value = self.sample()
        value['rss_checkpoints_bytes'][100] = value['warm_rss_bytes'] + 4 * 1024 * 1024 + 4096
        result = self.evaluate(value)
        self.assertFalse(result['requirements']['rss_growth'])
        self.assertTrue(result['requirements']['rss_late_plateau'])

    def test_late_oscillation_is_not_mistaken_for_flat_quartiles(self):
        value = self.sample()
        base = value['warm_rss_bytes']
        value['rss_checkpoints_bytes'] = [base] * 361
        value['rss_checkpoints_bytes'][241:301] = [base + 260 * 1024] * 60
        result = self.evaluate(value)
        self.assertTrue(result['requirements']['rss_quarter_drift'])
        self.assertFalse(result['requirements']['rss_late_plateau'])

    def test_wall_clock_tail_is_not_substituted_with_cpu_time(self):
        value = self.control[43]
        before = copy.deepcopy(value)
        result = assess(value, 43, value['cpu'])
        self.assertEqual(result['steady']['max_ns'], 102033192)
        self.assertEqual(value['raw_cpu_ns'][714], 3772198)
        self.assertLess(result['measured_loop_wall_seconds'], result['simulated_seconds'])
        self.assertEqual(value, before)


if __name__ == '__main__':
    unittest.main()
