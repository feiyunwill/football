"""Performance evidence must distinguish a gain, equality and a slowdown."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "checks"))
# 2026-09-09: also validate instrumentation coverage, not just zero counters.
# from ecs_performance import paired_summary, same_trajectory
from ecs_performance import paired_summary, same_trajectory, profile_failures
import copy

class PairedPerformanceTest(unittest.TestCase):
    def test_zero_allocations_do_not_hide_missing_instrumentation(self):
        old = dict(hotspot_profile=True, steps_seen=4200, buckets=[
            dict(name=name, calls=2000 if name == "frame" else 20000, ns=100, allocations=50000, bytes=1000000)
            for name in ("frame", "players", "physics_sync", "collisions_cache", "full_cache")])
        old["buckets"][-1]["allocations"] = 40000
        new = copy.deepcopy(old)
        new["buckets"][0].update(allocations=10000, bytes=360000)
        new["buckets"][-1].update(allocations=0, bytes=0)
        pair = dict(seed=42, baseline=old, candidate=new)
        self.assertFalse(profile_failures(pair))
        new["buckets"][-1].update(calls=0, ns=0)
        self.assertTrue(profile_failures(pair))

    def test_equal_measurements_do_not_prove_a_gain(self):
        result = paired_summary([(100, 100)] * 5)
        self.assertEqual(result["bootstrap_95_upper"], 1)

    def test_consistent_improvement_has_interval_below_one(self):
        result = paired_summary([(100, 80), (110, 88), (120, 96), (90, 72), (200, 160)])
        self.assertLess(result["bootstrap_95_upper"], .81)
        self.assertAlmostEqual(result["geometric_ratio"], .8)

    def test_slowdown_and_insufficient_repeats_are_rejected(self):
        self.assertGreater(paired_summary([(100, 120)] * 5)["bootstrap_95_lower"], 1)
        with self.assertRaises(RuntimeError):
            paired_summary([(100, 90)] * 4)

    def test_midmatch_drift_cannot_hide_behind_equal_final_state(self):
        left = dict(seed=42, input_hash="input", warm_hash="warm", final_hash="final",
                    state_checkpoints=["warm", "middle", "final"], active_flags=[1,1])
        right = dict(left, state_checkpoints=["warm", "different", "final"])
        with self.assertRaisesRegex(RuntimeError, "state_checkpoints"):
            same_trajectory(left, right)
