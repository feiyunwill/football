"""Negative controls for performance evidence; these fixtures are not measured results."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "checks"))
import match_benchmark as benchmark


class BenchmarkEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.result = {
            "passed": True, "skipped": 0, "assertions": 14, "format": 1, "seed": 42,
            "warmup_frames": 2, "measured_frames": 4, "cpu": 0, "players": [11, 11],
            "slots": [2, 2], "physics_ticks_per_frame": 10, "logical_frame_budget_ns": 100000000,
            "snapshot_replay": True, "raw_warmup_ns": [9, 3], "raw_frame_ns": [10, 40, 20, 30],
            "raw_cpu_ns": [9, 39, 19, 29], "active_flags": [1, 1, 0, 0],
            "warmup": {"count": 2, "sum_ns": 12, "p50_ns": 3, "p95_ns": 9, "p99_ns": 9, "max_ns": 9},
            "steady": {"count": 4, "sum_ns": 100, "p50_ns": 20, "p95_ns": 40, "p99_ns": 40, "max_ns": 40},
            "cpu_time": {"count": 4, "sum_ns": 96, "p50_ns": 19, "p95_ns": 39, "p99_ns": 39, "max_ns": 39},
            "active": {"count": 2, "sum_ns": 50, "p50_ns": 10, "p95_ns": 40, "p99_ns": 40, "max_ns": 40},
            "stopped": {"count": 2, "sum_ns": 50, "p50_ns": 20, "p95_ns": 30, "p99_ns": 30, "max_ns": 30},
            "input_hash": "c" * 16, "warm_hash": "a" * 16, "final_hash": "b" * 16,
            "state_checkpoints": ["a" * 16, "b" * 16], "rss_checkpoints_bytes": [4096, 8192],
            "loop_wall_ns": 110, "diagnostics_ns": 5, "actual_start_ms": 200, "actual_end_ms": 600,
            "kicked_history_frames": 1,
        }
        for key in ("initial_rss_bytes", "startup_rss_bytes", "warm_rss_bytes", "final_rss_bytes",
                    "closed_rss_bytes", "peak_rss_bytes", "startup_ns", "close_ns"):
            self.result[key] = 4096

    def validate(self):
        return benchmark.validate_run(self.result, 42, 2, 4, 0)

    def test_valid_raw_evidence_and_nearest_rank(self):
        self.assertGreaterEqual(self.validate(), 40)

    def test_tampered_quantile_is_rejected(self):
        self.result["steady"]["p99_ns"] = 20
        with self.assertRaisesRegex(RuntimeError, "Summary differs"):
            self.validate()

    def test_missing_and_invalid_raw_samples_are_rejected(self):
        for values in ([10, 20], [True, 40, 20, 30], [0, 40, 20, 30]):
            with self.subTest(values=values):
                self.result["raw_frame_ns"] = values
                with self.assertRaisesRegex(RuntimeError, "Invalid raw samples"):
                    self.validate()

    def test_stopped_or_nonadvancing_simulation_is_rejected(self):
        self.result["actual_end_ms"] = 599
        with self.assertRaisesRegex(RuntimeError, "timeline"):
            self.validate()
        self.result["actual_end_ms"] = 600
        self.result["active_flags"] = [0, 0, 0, 0]
        with self.assertRaisesRegex(RuntimeError, "in-play"):
            self.validate()

    def test_diagnostic_cost_cannot_be_hidden_inside_frames(self):
        self.result["loop_wall_ns"] = 104
        with self.assertRaisesRegex(RuntimeError, "overlap"):
            self.validate()

    def test_missing_replay_or_players_are_rejected(self):
        for key, value in (("snapshot_replay", False), ("players", [1, 1]), ("skipped", 1)):
            with self.subTest(key=key):
                original = self.result[key]
                self.result[key] = value
                with self.assertRaises(RuntimeError):
                    self.validate()
                self.result[key] = original

    def test_repetitions_reject_missing_process_and_trajectory_drift(self):
        results = [dict(copy.deepcopy(self.result), seed=seed) for seed in (42, 43, 42, 43)]
        self.assertGreater(benchmark.validate_repeats(results, 2), 0)
        with self.assertRaisesRegex(RuntimeError, "Missing independent"):
            benchmark.validate_repeats(results[:-1], 2)
        results[2]["state_checkpoints"][0] = "d" * 16
        with self.assertRaisesRegex(RuntimeError, "Nondeterministic"):
            benchmark.validate_repeats(results, 2)

    def test_missing_or_stationary_trajectory_is_rejected(self):
        self.result["state_checkpoints"] = []
        with self.assertRaisesRegex(RuntimeError, "trajectory checkpoints"):
            self.validate()
        self.result["state_checkpoints"] = ["a" * 16, "a" * 16]
        self.result["final_hash"] = "a" * 16
        with self.assertRaisesRegex(RuntimeError, "Stationary"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
