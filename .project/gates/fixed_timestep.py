"""Accept the current 50 Hz match cadence from independently verified product runs.

The input gate owns the costly Release/sanitizer/window executions. This gate
checks their complete receipts against current files, then joins them to the
framework's Python cadence and pacing tests. It never counts old or stale runs.
"""

import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".project"))
from quality import Program, file_hash  # noqa: E402


class AcceptanceError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def checked_files(entries, base, *, absolute=False):
    count = 0
    for name, expected in entries.items():
        path = Path(name) if absolute else base / name
        resolved = path.resolve()
        require(path.is_absolute() if absolute else resolved.is_relative_to(base.resolve()),
                f"Evidence path escaped its scope: {name}")
        digest = expected if isinstance(expected, str) else expected["sha256"]
        require(resolved.is_file() and file_hash(resolved) == digest,
                f"Evidence file changed or disappeared: {name}")
        count += 1
    return count


def main():
    program = Program(ROOT)
    for name in ("framework_regression", "input_contract"):
        require(program.check_state(name) == "verified", f"Current {name} evidence is required")

    record = json.loads((program.evidence_dir / "input_contract.json").read_text())
    log = program.evidence_dir / record["log"]
    summary = json.loads(log.read_text().splitlines()[-1])
    artifact = Path(summary["artifact"]).resolve()
    benchmarks = ROOT / ".project/optimization/benchmarks"
    require(artifact.is_relative_to(benchmarks) and artifact.name == "report.json",
            "Input report is outside the benchmark evidence directory")
    require(artifact.is_file() and file_hash(artifact) == summary["artifact_sha256"],
            "Input report digest does not match the verified run")
    report = json.loads(artifact.read_text())
    require(summary["passed"] is True and report["passed"] is True and
            summary["skipped"] == report["skipped"] == 0 and
            summary["assertions"] == report["assertions"] >= 2_150_000,
            "Incomplete current input contract")
    require(all(report.get(name) is True for name in
                ("actual_gameenv", "actual_x11", "actual_xtest", "actual_native_mains")),
            "Input evidence omitted the real product path")

    integrity = {
        "sources": checked_files(report["sources"], ROOT),
        "binaries": checked_files(report["binaries"], ROOT, absolute=True),
        "dependencies": checked_files(report["dependencies"], ROOT, absolute=True),
        "artifacts": checked_files(report["artifacts"], artifact.parent),
    }
    require(integrity["sources"] >= 1_000 and integrity["artifacts"] >= 100,
            "Input run has an incomplete file receipt")

    native = {}
    selected = ("engine_native_match_contract", "engine_native_publication_clock_contract",
                "engine_native_input_timeline_contract", "clock-replay")
    for mode in ("release", "sanitized"):
        native[mode] = {}
        for target in selected:
            row = report["results"][f"{mode}-{target}"]
            require(row["passed"] is True and row["skipped"] == 0 and row["assertions"] > 0,
                    f"Missing {mode} {target} coverage")
            native[mode][target] = row
        require(native[mode]["engine_native_match_contract"]["actual_gameenv"] is True and
                native[mode]["engine_native_match_contract"]["engine_frames"] >= 600 and
                native[mode]["engine_native_match_contract"]["clock_events"] >= 10_000,
                f"{mode} did not advance the actual engine at the declared cadence")
        require(native[mode]["engine_native_publication_clock_contract"]["cadence_frames"] >= 6_000 and
                native[mode]["engine_native_publication_clock_contract"]["edge_frames"] >= 6 and
                native[mode]["engine_native_input_timeline_contract"]["offline_frames"] >= 30_000,
                f"{mode} omitted busy/idle input edge or timeline coverage")

    cases = report["windows"]["probe_result"]["cases"]
    require({row["kind"] for row in cases} == {"standalone", "tcp", "udp"},
            "Missing one of the three real product entries")
    for row in cases:
        measure = row["measurements"]
        require(row["passed"] is True and row["actual_product_main"] is True and
                row["actual_xtest"] is True and measure["actual_in_play"] is True and
                measure["held_local_neutral"] == 0 and measure["held_local_frames"] >= 50,
                f"Product {row['kind']} lost held input or device coverage")
        if row["kind"] != "standalone":
            authority = row["authority"]
            require(measure["continuous_held_authority_verified"] is True and
                    measure["held_authority_neutral"] == 0 and
                    measure["held_authority_frames"] >= 50 and
                    authority["frames"] >= 100 and authority["actual_saved_confirmed_inputs"] is True,
                    f"Product {row['kind']} lost an authority frame")
            require(all(measure["clearing_frames"].get(key, 0) >= 3 for key in
                        ("release", "focus_loss", "controls_paused", "resume_held_barrier")) and
                    measure["resume_repressed_frames"] >= 3,
                    f"Product {row['kind']} retained an input edge across a reset")

    replay_frames = sum(row["authority"]["frames"] for row in cases if row["authority"])
    for mode in native:
        row = native[mode]["clock-replay"]
        require(row["actual_gameenv"] is True and row["replay_frames"] == replay_frames and
                row["clock_events"] >= 40_000,
                f"{mode} did not independently replay every network authority frame")

    framework = json.loads((program.evidence_dir / "framework_regression.json").read_text())
    junit = program.evidence_dir / "framework-pytest.xml"
    require(framework["started"] <= junit.stat().st_mtime <=
            framework["started"] + framework["duration_seconds"] + 2,
            "Python cadence JUnit is not from the verified framework run")
    tests = list(ET.parse(junit).getroot().iter("testcase"))
    suites = {
        "gfootball.frame_sync.test_frame_pacing": 13,
        "gfootball.frame_sync.test_match_cadence": 13,
        "gfootball.frame_sync.test_product_cadence": 10,
    }
    selected_tests = [case for case in tests if any(
        case.get("classname", "").startswith(prefix + ".") for prefix in suites)]
    for prefix, minimum in suites.items():
        require(sum(case.get("classname", "").startswith(prefix + ".") for case in selected_tests)
                >= minimum, f"Python cadence suite is incomplete: {prefix}")
    require(len(selected_tests) >= 36 and all(not any(
        case.find(kind) is not None for kind in ("failure", "error", "skipped"))
        for case in selected_tests), "Python cadence/pacing tests failed or skipped")
    names = {case.get("name") for case in selected_tests}
    for name in ("test_product_absolute_grid_and_stall_preserve_input_edges",
                 "test_actual_native_scaled_termination_and_midmatch_restore",
                 "test_both_transports_confirm_before_frame_zero_and_after_reconnect",
                 "test_stall_discards_schedule_debt_without_a_catchup_burst",
                 "test_waiting_retry_stall_and_correction_never_resample_a_sent_frame"):
        require(name in names, f"Critical cadence regression is missing: {name}")

    output = benchmarks / f"fixed-timestep-{time.time_ns()}"
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "passed": True,
        "skipped": 0,
        "assertions": len(selected_tests) + len(selected) * 2 + len(cases) + 5,
        "reused_current_evidence": True,
        "input_report": str(artifact),
        "input_report_sha256": summary["artifact_sha256"],
        "framework_junit": str(junit),
        "framework_junit_sha256": file_hash(junit),
        "integrity_files": integrity,
        "python_cadence_tests": len(selected_tests),
        "native_modes": list(native),
        "product_entries": {row["kind"]: row["authority"]["frames"] if row["authority"] else None
                            for row in cases},
        "replay_frames_per_mode": replay_frames,
        "scope": "50 Hz contract, physics steps, busy/idle edges and actual product authority; "
                 "does not accept device-to-player latency or rendering performance",
    }
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
