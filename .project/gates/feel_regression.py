#!/usr/bin/env python3
"""Accept real-window input only when the controlled player responds within 50 ms."""

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import time


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / ".project/optimization/benchmarks"
EVIDENCE = ROOT / ".project/optimization/evidence"
DIAGNOSTICS = ROOT / ".project/optimization/diagnostics"
SEEDS = range(42, 57)
CYCLES = 4
SAMPLES = len(SEEDS) * CYCLES
BUDGET_MS = 50.0


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def p95(values):
    return sorted(values)[math.ceil(.95 * len(values)) - 1] if values else None


def source_manifest():
    program = json.loads((ROOT / ".project/optimization/program.json").read_text())
    check = next(item for item in program["checks"] if item["id"] == "feel_regression")
    result = {}
    for pattern in check["sources"]:
        paths = [path for path in ROOT.glob(pattern) if path.is_file()]
        require(paths, f"Empty feel acceptance source scope: {pattern}")
        for path in paths:
            resolved = path.resolve()
            require(resolved.is_relative_to(ROOT), "Feel acceptance source escapes checkout")
            result[path.relative_to(ROOT).as_posix()] = sha(path)
    return dict(sorted(result.items()))


def run(argv, log, *, environment=None, timeout=1800):
    with log.open("w") as stream:
        completed = subprocess.run([str(arg) for arg in argv], cwd=ROOT,
                                   env=environment, stdout=stream,
                                   stderr=subprocess.STDOUT, timeout=timeout)
    require(completed.returncode == 0, f"Feel acceptance command failed: {log}")
    return {"argv": list(map(str, argv)), "log": log.name, "log_sha256": sha(log),
            "returncode": completed.returncode}


def evaluate(cohort, output, binaries, sources):
    failures = []
    assertions = 0

    def check(condition, message):
        nonlocal assertions
        assertions += 1
        if not condition:
            failures.append(message)

    check(cohort.get("diagnostic_complete") is True, "Product cohort is incomplete")
    check(cohort.get("actual_product_main") is True and cohort.get("actual_xtest") is True,
          "Actual standalone window and XTEST were not measured")
    check(cohort.get("render_backend") == "private_d3d12" and
          cohort.get("command_trace_enabled") is True,
          "Measured renderer or command trace differs from the product contract")
    check(cohort.get("engine_core_sha256") == binaries["engine"],
          "Product cohort loaded a different engine")
    check(cohort.get("source_sha256") == sources[
          ".project/optimization/diagnostics/feel_latency_cohort.py"] and
          cohort.get("window_source_sha256") == sources[
          ".project/optimization/diagnostics/feel_latency_window.py"],
          "Product cohort used different measurement code")
    matches = cohort.get("matches", [])
    samples = cohort.get("samples", [])
    check(len(matches) == len(SEEDS) and [row.get("seed") for row in matches] == list(SEEDS),
          "Missing or reordered independent product matches")
    check(len(samples) == SAMPLES and cohort.get("total_presses") == SAMPLES,
          "Incomplete physical input cohort")
    all_samples = []
    for seed in SEEDS:
        directory = output / "cohort" / f"seed-{seed}"
        report_path = directory / "report.json"
        require(report_path.is_file(), f"Missing product report for seed {seed}")
        report = json.loads(report_path.read_text())
        row = matches[seed - SEEDS.start] if len(matches) == len(SEEDS) else {}
        check(row.get("path") == f"seed-{seed}/report.json" and
              row.get("sha256") == sha(report_path),
              f"Product report identity changed for seed {seed}")
        check(report.get("seed") == seed and report.get("cycles") == CYCLES and
              len(report.get("samples", [])) == CYCLES,
              f"Product match workload changed for seed {seed}")
        check(report.get("actual_product_main") is True and
              report.get("actual_xtest") is True and
              report.get("actual_player_velocity") is True,
              f"Product player observation missing for seed {seed}")
        check(report.get("product_mapped_engine_core") is True and
              report.get("engine_core_sha256") == binaries["engine"] and
              report.get("product_sha256") == binaries["product"],
              f"Product binary identity changed for seed {seed}")
        check(report.get("product_mapped_private_driver") is True and
              report.get("driver_sha256") == binaries["driver"] and
              report.get("render_backend") == "private_d3d12",
              f"Actual D3D12 renderer missing for seed {seed}")
        check(report.get("trace_library_sha256") == binaries["trace"] and
              report.get("command_trace_enabled") is True,
              f"Command attribution was not active for seed {seed}")
        check(report.get("trace_sha256") == sha(directory / "trace/events.jsonl") and
              report.get("actions_sha256") == sha(directory / "actions.json"),
              f"Raw replay evidence changed for seed {seed}")
        check(report.get("source_sha256") == sources[
              ".project/optimization/diagnostics/feel_latency_window.py"] and
              report.get("trace_source_sha256") == sources[
              "engine/tests/engine_native_window_trace.cpp"] and
              report.get("keyboard_source_sha256") == sources[
              ".project/checks/native_input_window_cases.py"],
              f"Product measurement source changed for seed {seed}")
        for index, sample in enumerate(report.get("samples", [])):
            check(sample.get("index") == index and sample.get("direction") in (-1, 1),
                  f"Invalid press identity for seed {seed}, press {index}")
            check(sample.get("owned_player", -1) >= 0 and
                  sample.get("input_admission_ms") is not None,
                  f"Press never reached the controlled player: seed {seed}, press {index}")
            check(sample.get("status") == "admitted" and
                  sample.get("velocity_response_ms") is not None,
                  f"No real player velocity response: seed {seed}, press {index}")
            check(sample.get("first_swap_after_response_ms") is not None,
                  f"No product display after response: seed {seed}, press {index}")
            all_samples.append(dict(sample, seed=seed))
    check(all_samples == samples, "Cohort samples differ from per-match raw reports")
    responses = [row["velocity_response_ms"] for row in all_samples
                 if row.get("velocity_response_ms") is not None]
    swaps = [row["first_swap_after_response_ms"] for row in all_samples
             if row.get("first_swap_after_response_ms") is not None]
    admissions = [row["input_admission_ms"] for row in all_samples
                  if row.get("input_admission_ms") is not None]
    check(len(admissions) == cohort.get("admitted_count") == SAMPLES,
          "Some physical presses were not admitted")
    check(len(responses) == cohort.get("response_count") == SAMPLES,
          "Some physical presses never changed actual player velocity")
    check(p95(responses) == cohort.get("velocity_response_p95_ms"),
          "Reported response p95 differs from raw measurements")
    check(p95(swaps) == cohort.get("swap_after_response_p95_ms"),
          "Reported visible response p95 differs from raw measurements")
    check(p95(responses) is not None and p95(responses) <= BUDGET_MS,
          "Actual player velocity response p95 exceeds 50 ms")
    check(p95(swaps) is not None and p95(swaps) <= BUDGET_MS,
          "Visible product response p95 exceeds 50 ms")
    return {"passed": not failures, "assertions": assertions, "skipped": 0,
            "failures": failures, "presses": len(all_samples),
            "admitted": len(admissions), "responded": len(responses),
            "response_p95_ms": p95(responses), "visible_p95_ms": p95(swaps),
            "input_admission_p95_ms": p95(admissions)}


def classify_delays(output):
    """Explain failed presses from raw commands without changing acceptance."""
    cases = []
    causes = Counter()
    for seed in SEEDS:
        directory = output / "cohort" / f"seed-{seed}"
        actions = json.loads((directory / "actions.json").read_text())
        report = json.loads((directory / "report.json").read_text())
        relevant = []
        with (directory / "trace/events.jsonl").open() as stream:
            for line in stream:
                event = json.loads(line)
                if event.get("kind") in ("human_command", "anim_select"):
                    relevant.append(event)
        require(len(actions) == len(report["samples"]) == CYCLES,
                f"Incomplete triage workload for seed {seed}")
        for action, sample in zip(actions, report["samples"]):
            require(action["index"] == sample["index"] and
                    action["direction"] == sample["direction"],
                    f"Triage press identity differs for seed {seed}")
            start, end = action["start_ns"], action["end_ns"]
            direction = action["direction"]
            human = [event for event in relevant
                     if event["kind"] == "human_command" and
                     start <= event["time"] < end and
                     event.get("hid_x") == direction]
            players = {event["player"] for event in human}
            selected = [event for event in relevant
                        if event["kind"] == "anim_select" and
                        start <= event["time"] < end and
                        event.get("player") in players]
            opposing = [event for event in human
                        if event.get("desired_x", 0) * direction < -0.1]
            aligned = [event for event in human
                       if event.get("desired_x", 0) * direction > 0.1]
            accepted_movement = [event for event in selected
                                 if event.get("accepted") is True and
                                 event.get("command_type") == 1 and
                                 aligned and event["time"] >= aligned[0]["time"] and
                                 event.get("desired_x", 0) * direction > 0.1]
            touch_pending = any(event.get("touch_pending") is True
                                for event in selected)
            response = sample.get("velocity_response_ms")
            visible = sample.get("first_swap_after_response_ms")
            violation = response is None or visible is None or max(response, visible) > BUDGET_MS
            first_human = (round((human[0]["time"] - start) / 1e6, 3)
                           if human else None)
            first_aligned = (round((aligned[0]["time"] - start) / 1e6, 3)
                             if aligned else None)
            first_accepted = (round((accepted_movement[0]["time"] - start) / 1e6, 3)
                              if accepted_movement else None)
            if not violation:
                cause = "within_budget"
            elif len(players) > 1:
                cause = "controlled_player_changed"
            elif not human:
                cause = "no_human_command_in_window"
            elif opposing and (not aligned or first_aligned > BUDGET_MS):
                cause = "assist_direction_conflict"
            elif touch_pending:
                cause = "touch_pending"
            elif first_human is not None and first_human > BUDGET_MS:
                cause = "late_command_sampling"
            elif first_accepted is None or first_accepted > BUDGET_MS:
                cause = "animation_selection_delay"
            elif response is None or response > BUDGET_MS:
                cause = "movement_physics_delay"
            else:
                cause = "presentation_delay"
            if violation:
                causes[cause] += 1
            cases.append({"seed": seed, "index": sample["index"],
                          "direction": direction, "owned_player": sample.get("owned_player"),
                          "violation": violation, "diagnostic_cause": cause,
                          "human_commands": len(human), "distinct_human_players": len(players),
                          "opposing_commands": len(opposing), "aligned_commands": len(aligned),
                          "touch_pending_observed": touch_pending,
                          "first_human_command_ms": first_human,
                          "first_aligned_command_ms": first_aligned,
                          "first_accepted_aligned_movement_ms": first_accepted,
                          "input_admission_ms": sample.get("input_admission_ms"),
                          "velocity_response_ms": response,
                          "first_swap_after_response_ms": visible})
    require(len(cases) == SAMPLES and
            sum(case["violation"] for case in cases) == sum(causes.values()),
            "Triage did not account for all product presses")
    return {"diagnostic_only": True, "classification_is_inference": True,
            "presses": len(cases), "violations": sum(causes.values()),
            "violation_causes": dict(sorted(causes.items())), "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gpu-driver-root", type=Path, default=Path(os.environ.get(
        "FOOTBALL_FEEL_GPU_DRIVER_ROOT",
        str(Path.home() / ".cache/football-mesa-build-20260913-a/install-candidate"))))
    args = parser.parse_args()
    require(platform.system() == "Linux" and sys.flags.optimize == 0,
            "Formal feel acceptance requires Linux and enabled Python assertions")
    build = args.build.resolve()
    output = (args.output or BENCHMARKS / f"feel-regression-{time.time_ns()}").resolve()
    require(output.is_relative_to(BENCHMARKS) and not output.exists(),
            "Use a new checkout-owned feel evidence directory")
    tools = Path(os.environ.get("FOOTBALL_TEST_X11_ROOT", str(
        Path.home() / ".cache/football-input-x11-20260913-a/root-relocated"))).resolve()
    driver = args.gpu_driver_root.resolve() / "lib/libgallium-26.2.2.so"
    require((tools / "usr/bin/Xvfb").is_file() and (tools / "usr/bin/xkbcomp").is_file(),
            "Private X11 input dependencies are missing")
    require(driver.is_file() and (driver.parent / "dri/d3d12_dri.so").is_file(),
            "Private D3D12 driver is missing")
    sources = source_manifest()
    output.mkdir(parents=True)
    (output / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")
    commands = []
    archive = EVIDENCE / f"feel_regression-{time.time_ns()}.tar.gz"
    result = None
    try:
        def command(argv, label, timeout=1800):
            entry = run(argv, output / f"{label}.log", timeout=timeout)
            commands.append(entry)
            (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")

        command(["cmake", "-S", ROOT / "engine", "-B", build,
                 "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_PYTHON_BINDINGS=OFF",
                 "-DFOOTBALL_ENABLE_SANITIZERS=OFF",
                 f"-DFOOTBALL_TEST_X11_ROOT={tools}",
                 f"-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / 'bin'}"], "configure")
        command(["cmake", "--build", build, "-j", "1", "--target",
                 "standalone_game", "engine_native_window_trace"], "build")
        binaries = {"engine": sha(build / "libfootball_engine.so"),
                    "product": sha(build / "bin/standalone_game"),
                    "trace": sha(build / "input-tests/libengine_native_window_trace.so"),
                    "driver": sha(driver)}
        (output / "binaries.json").write_text(json.dumps(binaries, indent=2) + "\n")
        command([sys.executable, DIAGNOSTICS / "feel_latency_cohort.py",
                 "--runs", len(SEEDS), "--cycles-per-run", CYCLES,
                 "--first-seed", SEEDS.start, "--trace-commands",
                 "--gpu-driver-root", args.gpu_driver_root.resolve(),
                 "--build", build, "--output", output / "cohort"],
                "product-cohort", timeout=1800)
        cohort = json.loads((output / "cohort/report.json").read_text())
        result = evaluate(cohort, output, binaries, sources)
        triage = classify_delays(output)
        triage_path = output / "triage.json"
        triage_path.write_text(json.dumps(triage, indent=2) + "\n")
        result.update(scope="15 independent real standalone-game windows, 4 XTEST presses each; "
                            "actual controlled-player velocity and following product swap",
                      seeds=list(SEEDS), budget_ms=BUDGET_MS,
                      source_sha256=sha(__file__), binaries=binaries,
                      driver_root=str(args.gpu_driver_root.resolve()),
                      x11_root=str(tools), cohort_sha256=sha(output / "cohort/report.json"),
                      triage_sha256=sha(triage_path),
                      triage_violations=triage["violations"],
                      triage_causes=triage["violation_causes"])
        require(source_manifest() == sources, "Feel acceptance sources changed during measurement")
        require(all(sha(path) == value for path, value in ((
            build / "libfootball_engine.so", binaries["engine"]),
            (build / "bin/standalone_game", binaries["product"]),
            (build / "input-tests/libengine_native_window_trace.so", binaries["trace"]),
            (driver, binaries["driver"]))), "Measured binary changed during acceptance")
        (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    except BaseException as error:
        (output / "failure.json").write_text(json.dumps({
            "error_type": type(error).__name__, "error": str(error),
            "commands": commands}, indent=2) + "\n")
        raise
    finally:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(output, arcname=output.name)
        print(json.dumps({"raw_archive": str(archive),
                          "raw_archive_sha256": sha(archive)}), flush=True)
    print(json.dumps({"passed": result["passed"], "assertions": result["assertions"],
                      "skipped": 0, "failures": result["failures"],
                      "artifact": str(output / "report.json"),
                      "artifact_sha256": sha(output / "report.json"),
                      "triage_sha256": result["triage_sha256"],
                      "triage_causes": result["triage_causes"],
                      "raw_archive": str(archive),
                      "raw_archive_sha256": sha(archive)}), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
