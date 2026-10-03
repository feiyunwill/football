"""Acceptance must notice nested fixtures and omitted native transport suites."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "checks"))
import framework_regression as framework
from input_contract import tactical_coverage, require_tactical_parity

spec = importlib.util.spec_from_file_location("acceptance_quality", PROJECT / "quality.py")
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)

BASELINE_EXISTING_CASES = 560
BASELINE_CASES = BASELINE_EXISTING_CASES + sum(framework.REQUIRED_CPP_SUITES.values())

FIXTURE_CHECKS = (
    "framework_regression", "state_ownership", "environment_lifetime",
    "simulation_contract", "architecture_regression", "match_benchmark",
    "ecs_performance", "memory_budget", "performance_regression",
    "input_contract", "tactical_integration", "ai_decisions",
)


class AcceptanceInputsTest(unittest.TestCase):
    def test_tactical_scenario_coverage_rejects_missing_or_hollow_cases(self):
        cases = [
            dict(seed=42, physics=2, actual_frames=240, nonzero_actors=960, restarts=0),
            dict(seed=42, physics=10, actual_frames=240, nonzero_actors=876, restarts=4),
            dict(seed=43, physics=2, actual_frames=240, nonzero_actors=960, restarts=0),
            dict(seed=43, physics=10, actual_frames=240, nonzero_actors=792, restarts=94),
        ]
        summary = dict(assertions=27456, frames=960, nonzero_actors=3588, restarts=98)
        raw = lambda rows: "\n".join(json.dumps(row) for row in rows)
        self.assertEqual(len(tactical_coverage(raw(cases), summary)[1]), 4)
        with self.assertRaisesRegex(RuntimeError, "matrix"):
            tactical_coverage(raw(cases[:-1]), summary)
        hollow = [dict(row) for row in cases]
        hollow[1]["restarts"] = 0
        with self.assertRaisesRegex(RuntimeError, "coverage"):
            tactical_coverage(raw(hollow), summary)
        hollow = [dict(row) for row in cases]
        hollow[3]["nonzero_actors"] = 719
        with self.assertRaisesRegex(RuntimeError, "coverage"):
            tactical_coverage(raw(hollow), summary)
        with self.assertRaisesRegex(RuntimeError, "totals"):
            tactical_coverage(raw(cases), dict(summary, restarts=99))
        coverage = tactical_coverage(raw(cases), summary)
        require_tactical_parity(coverage, coverage)
        with self.assertRaisesRegex(RuntimeError, "Release/Sanitizer"):
            require_tactical_parity(coverage, (coverage[0], coverage[1][:-1]))

    def test_nested_fixture_content_and_addition_invalidate_each_gate(self):
        manifest = json.loads((PROJECT / "optimization/program.json").read_text(encoding="utf-8"))
        checks = {check["id"]: check for check in manifest["checks"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shallow = root / "engine/tests/fixtures/base.inc"
            nested = root / "engine/tests/fixtures/native_udp/listener/routing_cases.inc"
            nested.parent.mkdir(parents=True)
            shallow.write_bytes(b"shallow")
            nested.write_bytes(b"original")
            for name in FIXTURE_CHECKS:
                with self.subTest(check=name):
                    fixture_patterns = [pattern for pattern in checks[name]["sources"]
                                        if pattern.startswith("engine/tests/fixtures/")]
                    self.assertTrue(fixture_patterns)
                    # Isolate the actual declared fixture scope; do not replace its glob.
                    check = dict(checks[name], sources=fixture_patterns)
                    program = object.__new__(quality.Program)
                    program.root = root
                    program.checks = {name: check}
                    nested.write_bytes(b"original")
                    with mock.patch.object(quality.shutil, "which", return_value=None):
                        before = program.fingerprint(name)
                        nested.write_bytes(b"changed")
                        changed = program.fingerprint(name)
                        self.assertNotEqual(before, changed)
                        extra = nested.parent / "new_case.inc"
                        extra.write_bytes(b"additional")
                        added = program.fingerprint(name)
                        self.assertNotEqual(changed, added)
                        extra.unlink()

    def report(self, root, cases):
        suite = ET.Element("testsuite")
        for name, outcome in cases:
            case = ET.SubElement(suite, "testcase", name=name)
            if outcome:
                ET.SubElement(case, outcome)
        path = root / "ctest.xml"
        ET.ElementTree(suite).write(path, encoding="utf-8")
        return path

    def baseline(self):
        cases = [(f"existing.case{i}", None) for i in range(BASELINE_EXISTING_CASES)]
        for prefix, count in framework.REQUIRED_CPP_SUITES.items():
            cases.extend((f"{prefix}case{i}", None) for i in range(count))
        return cases

    def test_complete_report_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.report(Path(directory), self.baseline())
            self.assertEqual(framework.junit_count(path, BASELINE_CASES, framework.REQUIRED_CPP_SUITES), BASELINE_CASES)

    def test_unrelated_cases_cannot_replace_any_required_suite(self):
        for prefix in framework.REQUIRED_CPP_SUITES:
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as directory:
                cases = [(name.replace(prefix, "unrelated.", 1) if name.startswith(prefix) else name, outcome)
                         for name, outcome in self.baseline()]
                path = self.report(Path(directory), cases)
                with self.assertRaisesRegex(RuntimeError, "Incomplete suite"):
                    framework.junit_count(path, BASELINE_CASES, framework.REQUIRED_CPP_SUITES)

    def test_partial_suite_is_rejected_even_with_enough_total_cases(self):
        for prefix in framework.REQUIRED_CPP_SUITES:
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as directory:
                cases = [(name if name != prefix + "case0" else "padding.case", outcome)
                         for name, outcome in self.baseline()]
                path = self.report(Path(directory), cases)
                with self.assertRaisesRegex(RuntimeError, "Incomplete suite"):
                    framework.junit_count(path, BASELINE_CASES, framework.REQUIRED_CPP_SUITES)

    def test_duplicate_test_names_cannot_pad_coverage(self):
        cases = self.baseline()
        cases[-1] = cases[-2]
        with tempfile.TemporaryDirectory() as directory:
            path = self.report(Path(directory), cases)
            with self.assertRaisesRegex(RuntimeError, "duplicate"):
                framework.junit_count(path, BASELINE_CASES, framework.REQUIRED_CPP_SUITES)

    def test_framework_requires_the_observation_runtime_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.report(Path(directory), [(name if not name.startswith("rl_observation_contract") else "padding.case", outcome)
                                                  for name, outcome in self.baseline()])
            with self.assertRaisesRegex(RuntimeError, "Incomplete suite rl_observation_contract"):
                framework.junit_count(path, BASELINE_CASES, framework.REQUIRED_CPP_SUITES)

    def test_framework_accepts_the_observation_runtime_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.report(Path(directory), self.baseline())
            self.assertEqual(framework.junit_count(path, BASELINE_CASES, framework.REQUIRED_CPP_SUITES), BASELINE_CASES)

    def test_failure_error_and_skip_are_rejected(self):
        for outcome in ("failure", "error", "skipped"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                cases = self.baseline()
                cases[-1] = (cases[-1][0], outcome)
                path = self.report(Path(directory), cases)
                with self.assertRaisesRegex(RuntimeError, "Failure, error or skipped"):
                    framework.junit_count(path, BASELINE_CASES, framework.REQUIRED_CPP_SUITES)


if __name__ == "__main__":
    unittest.main()
