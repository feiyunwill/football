"""Acceptance infrastructure must reject false completion and stale evidence."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).resolve().parents[1] / "quality.py"
spec = importlib.util.spec_from_file_location("quality", RUNNER)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


class QualityTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "source.txt").write_text("original")
        self.path = self.root / ".project/optimization/program.json"
        self.manifest = {
            "version": 1,
            "checks": [{"id": "sample", "acceptance": ["real assertions"], "ready": True,
                        "argv": [sys.executable, "-c", 'print(\'{"passed": true, "assertions": 3}\')'],
                        "kind": "json", "min_assertions": 3, "timeout": 10,
                        "sources": ["source.txt"]}],
            "nodes": [
                {"id": "ms-19.1", "kind": "milestone", "title": "Milestone", "children": ["plan-19.1"],
                 "acceptance": ["integration"], "checks": ["sample"]},
                {"id": "plan-19.1", "kind": "plan", "title": "Plan", "children": ["task-19.1"],
                 "acceptance": ["integration"], "checks": ["sample"]},
                {"id": "task-19.1", "kind": "task", "title": "Task", "acceptance": ["assertions"], "checks": ["sample"]},
            ],
        }

    def program(self):
        quality.atomic_json(self.path, self.manifest)
        return quality.Program(self.root)

    def run_program(self, program=None):
        program = program or self.program()
        with contextlib.redirect_stdout(io.StringIO()):
            program.run("ms-19.1")
        return program

    def test_initial_state_requires_evidence(self):
        self.assertEqual(set(self.program().states().values()), {"pending"})

    def test_success_propagates_from_task_to_milestone(self):
        self.assertEqual(set(self.run_program().states().values()), {"verified"})

    def test_source_change_invalidates_whole_hierarchy(self):
        program = self.run_program()
        (self.root / "source.txt").write_text("changed")
        self.assertEqual(set(program.states().values()), {"stale"})

    def test_new_source_matching_glob_invalidates_evidence(self):
        self.manifest["checks"][0]["sources"] = ["*.txt"]
        program = self.run_program()
        (self.root / "second.txt").write_text("new code")
        self.assertEqual(program.check_state("sample"), "stale")

    def test_changed_threshold_invalidates_evidence(self):
        self.run_program()
        self.manifest["checks"][0]["min_assertions"] = 4
        self.assertEqual(self.program().check_state("sample"), "stale")

    def test_changed_toolchain_invalidates_evidence(self):
        tool = self.root / "compiler"
        tool.write_text("#!/bin/sh\nexit 0\n")
        tool.chmod(0o700)
        self.manifest["checks"][0]["tools"] = [str(tool)]
        program = self.run_program()
        tool.write_text("#!/bin/sh\nexit 1\n")
        self.assertEqual(program.check_state("sample"), "stale")

    def test_changed_declared_environment_invalidates_evidence(self):
        self.manifest["checks"][0]["environment"] = ["FOOTBALL_QUALITY_TEST_CONFIG"]
        program = self.run_program()
        original = os.environ.get("FOOTBALL_QUALITY_TEST_CONFIG")
        try:
            os.environ["FOOTBALL_QUALITY_TEST_CONFIG"] = "changed configuration"
            self.assertEqual(program.check_state("sample"), "stale")
        finally:
            if original is None:
                os.environ.pop("FOOTBALL_QUALITY_TEST_CONFIG", None)
            else:
                os.environ["FOOTBALL_QUALITY_TEST_CONFIG"] = original

    def test_deleted_log_invalidates_evidence(self):
        program = self.run_program()
        for path in program.evidence_dir.glob("*.log"):
            path.unlink()
        self.assertEqual(program.check_state("sample"), "invalid")

    def test_modified_log_invalidates_evidence(self):
        program = self.run_program()
        for path in program.evidence_dir.glob("*.log"):
            path.write_text("modified")
        self.assertEqual(program.check_state("sample"), "invalid")

    def test_corrupt_record_cannot_complete(self):
        program = self.run_program()
        (program.evidence_dir / "sample.json").write_text("{bad")
        self.assertEqual(program.check_state("sample"), "invalid")

    def test_nonzero_exit_cannot_be_masked_by_success_output(self):
        self.manifest["checks"][0]["argv"][-1] += "; raise SystemExit(7)"
        program = self.program()
        with self.assertRaises(quality.QualityError):
            self.run_program(program)
        self.assertEqual(program.states()["ms-19.1"], "failed")

    def test_planned_check_cannot_run_or_verify(self):
        self.manifest["checks"][0] = {"id": "sample", "ready": False, "acceptance": ["future integration"]}
        program = self.program()
        with self.assertRaisesRegex(quality.QualityError, "planned"):
            program.run("task-19.1")
        self.assertEqual(program.states()["ms-19.1"], "planned")

    def test_missing_executable_is_failed_evidence(self):
        self.manifest["checks"][0]["argv"] = [str(self.root / "missing-program")]
        program = self.program()
        with self.assertRaises(quality.QualityError):
            self.run_program(program)
        self.assertEqual(program.check_state("sample"), "failed")

    def test_source_mutation_during_check_is_rejected(self):
        self.manifest["checks"][0]["argv"][-1] += '; open("source.txt", "w").write("modified")'
        with self.assertRaises(quality.QualityError):
            self.run_program()

    def test_timeout_is_failed_and_cleans_up_descendants(self):
        self.manifest["checks"][0]["timeout"] = 0.15
        # If a timeout leaves descendants running this file will appear later.
        child = 'import time; time.sleep(.4); open("leaked.txt", "w").write("leak")'
        self.manifest["checks"][0]["argv"][-1] = (
            f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
        )
        program = self.program()
        with self.assertRaises(quality.QualityError):
            self.run_program(program)
        subprocess.run([sys.executable, "-c", "import time; time.sleep(.5)"], check=True)
        self.assertFalse((self.root / "leaked.txt").exists())
        self.assertEqual(program.check_state("sample"), "failed")

    def test_concurrent_runner_is_rejected_and_lock_recovers(self):
        program = self.program()
        with quality.exclusive_lock(program.evidence_dir / "run.lock"):
            with self.assertRaisesRegex(quality.QualityError, "concurrent builds"):
                program.run("task-19.1")
        self.run_program(program)

    def test_duplicate_id_is_rejected(self):
        self.manifest["nodes"].append(copy.deepcopy(self.manifest["nodes"][-1]))
        with self.assertRaisesRegex(quality.QualityError, "duplicate"):
            self.program()

    def test_missing_dependency_is_rejected(self):
        self.manifest["nodes"][-1]["depends_on"] = ["missing"]
        with self.assertRaisesRegex(quality.QualityError, "Missing dependency"):
            self.program()

    def test_dependency_cycle_is_rejected(self):
        self.manifest["nodes"][-1]["depends_on"] = ["ms-19.1"]
        with self.assertRaisesRegex(quality.QualityError, "cycle"):
            self.program()

    def test_ungated_task_is_rejected(self):
        self.manifest["nodes"][-1]["checks"] = []
        with self.assertRaisesRegex(quality.QualityError, "Missing acceptance"):
            self.program()

    def test_multiple_parents_are_rejected(self):
        extra = copy.deepcopy(self.manifest["nodes"][1])
        extra["id"] = "plan-19.2"
        self.manifest["nodes"][0]["children"].append(extra["id"])
        self.manifest["nodes"].append(extra)
        with self.assertRaisesRegex(quality.QualityError, "multiple parents"):
            self.program()

    def test_empty_source_glob_is_rejected(self):
        self.manifest["checks"][0]["sources"] = ["missing/*.cpp"]
        with self.assertRaisesRegex(quality.QualityError, "matched no files"):
            self.program().fingerprint("sample")

    def test_source_cannot_escape_workspace(self):
        self.manifest["checks"][0]["sources"] = ["../*.txt"]
        with self.assertRaisesRegex(quality.QualityError, "escapes workspace"):
            self.program().fingerprint("sample")

    def test_success_without_assertions_is_rejected(self):
        check = self.manifest["checks"][0]
        for output in ('{"passed": true, "assertions": 0}', '{"passed": true, "assertions": true}',
                       '{"passed": true, "assertions": 3, "skipped": 1}', "success", ""):
            with self.subTest(output=output):
                self.assertFalse(quality.Program.assess(check, 0, output)[0])

    def test_unittest_zero_and_skipped_tests_are_rejected(self):
        check = dict(self.manifest["checks"][0], kind="unittest")
        for output in ("Ran 0 tests in 0s\nOK\n", "Ran 3 tests in 0s\nOK (skipped=1)\n"):
            self.assertFalse(quality.Program.assess(check, 0, output)[0])
        self.assertTrue(quality.Program.assess(check, 0, "Ran 3 tests in 0.3s\n\nOK\n")[0])

    def test_missing_child_evidence_blocks_parent(self):
        program = self.run_program()
        task = copy.deepcopy(self.manifest["nodes"][-1])
        task.update(id="task-19.2", checks=["integration"])
        check = copy.deepcopy(self.manifest["checks"][0])
        check["id"] = "integration"
        self.manifest["checks"].append(check)
        self.manifest["nodes"].append(task)
        self.manifest["nodes"][1]["children"].append(task["id"])
        program = self.program()
        self.assertEqual(program.states()["task-19.1"], "verified")
        self.assertEqual(program.states()["ms-19.1"], "pending")

    def test_cli_verify_returns_nonzero_before_and_zero_after_checks(self):
        program = self.program()
        command = [sys.executable, str(RUNNER), "verify", "ms-19.1", "--root", str(self.root)]
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.run_program(program)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_docs_are_utf8_and_idempotent(self):
        program = self.program()
        program.docs()
        path = self.root / ".project/tasks/task-19.1.md"
        modified = path.stat().st_mtime_ns
        self.assertIn("验收", path.read_text(encoding="utf-8"))
        program.docs()
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_legacy_entrypoints_cannot_bypass_acceptance(self):
        program = self.program()
        scripts = self.root / ".project/scripts"
        scripts.mkdir()
        for name in ("quality_route.sh", "task_complete.sh", "plan_complete.sh", "milestone_complete.sh", "workflow.sh"):
            shutil.copy2(RUNNER.parent / "scripts" / name, scripts / name)
        shutil.copy2(RUNNER, self.root / ".project/quality.py")
        commands = [("task_complete.sh", "task-19.1"), ("plan_complete.sh", "plan-19.1"),
                    ("milestone_complete.sh", "ms-19.1"), ("workflow.sh", "complete", "ms-19.1")]
        for command in commands:
            result = subprocess.run(["bash", str(scripts / command[0]), *command[1:]], capture_output=True)
            self.assertNotEqual(result.returncode, 0, command)
        self.run_program(program)
        for command in commands:
            result = subprocess.run(["bash", str(scripts / command[0]), *command[1:]], capture_output=True)
            self.assertEqual(result.returncode, 0, (command, result.stderr.decode()))


if __name__ == "__main__":
    unittest.main()
