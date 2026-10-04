"""Aggregate short actual-window matches without counting set pieces as movement."""

import argparse
import collections
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WINDOW = Path(__file__).with_name("feel_latency_window.py")
BENCHMARKS = ROOT / ".project/optimization/benchmarks"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def p95(values):
    return sorted(values)[math.ceil(.95 * len(values)) - 1] if len(values) >= 20 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--cycles-per-run", type=int, default=6)
    parser.add_argument("--first-seed", type=int, default=42)
    parser.add_argument("--gpu-driver-root", type=Path, required=True)
    parser.add_argument("--trace-commands", action="store_true")
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    require(4 <= args.runs <= 20 and 4 <= args.cycles_per_run <= 10 and
            0 <= args.first_seed <= 2**32 - args.runs,
            "Cohort size or seed range is invalid")
    output = (args.output or BENCHMARKS / f"feel-cohort-{time.time_ns()}").resolve()
    require(output.is_relative_to(BENCHMARKS) and not output.exists(),
            "Use a new workspace evidence directory")
    output.mkdir(parents=True)
    source_sha = sha(WINDOW)
    reports = []
    samples = []
    excluded_transitions = []
    core_sha = None
    try:
        for offset in range(args.runs):
            seed = args.first_seed + offset
            directory = output / f"seed-{seed}"
            argv = [sys.executable, str(WINDOW), "--cycles", str(args.cycles_per_run),
                    "--seed", str(seed), "--build", str(args.build),
                    "--gpu-driver-root", str(args.gpu_driver_root),
                    "--output", str(directory)]
            if args.trace_commands:
                argv.append("--trace-commands")
            log = output / f"seed-{seed}.log"
            with log.open("w") as stream:
                completed = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                           stderr=subprocess.STDOUT, timeout=120)
            require(completed.returncode == 0, f"Actual product match {seed} failed: {log}")
            report_path = directory / "report.json"
            report = json.loads(report_path.read_text())
            require(report["seed"] == seed and report["source_sha256"] == source_sha and
                    report["actual_product_main"] and report["actual_xtest"] and
                    report["product_mapped_private_driver"] and
                    report["product_mapped_engine_core"] and
                    report["command_trace_enabled"] == args.trace_commands,
                    f"Actual product identity failed in match {seed}")
            core_sha = core_sha or report["engine_core_sha256"]
            require(report["engine_core_sha256"] == core_sha,
                    "Product engine core changed during cohort")
            excluded = report.get("excluded_unplayable_transitions", [])
            require(report.get("physical_presses") == args.cycles_per_run + len(excluded)
                    and len(excluded) <= 1 and all(
                        row.get("reason") == "play_ended_before_first_step"
                        for row in excluded),
                    f"Unbounded or unattributed transition retry in match {seed}")
            excluded_transitions.extend(dict(row, seed=seed) for row in excluded)
            reports.append({"seed": seed, "path": str(report_path.relative_to(output)),
                            "sha256": sha(report_path),
                            "admitted_count": report["admitted_count"],
                            "response_count": report["response_count"]})
            samples.extend(dict(row, seed=seed) for row in report["samples"])
            print(json.dumps({"seed": seed, "admitted": report["admitted_count"],
                              "responded": report["response_count"]}), flush=True)
        require(sha(WINDOW) == source_sha, "Window probe changed during cohort")
        admitted = [row for row in samples if row.get("input_admission_ms") is not None]
        responded = [row for row in samples if row.get("velocity_response_ms") is not None]
        report = {"diagnostic_complete": True, "formal_product_acceptance": False,
                  "acceptance_passed": False, "actual_product_main": True,
                  "actual_xtest": True, "render_backend": "private_d3d12",
                  "engine_core_sha256": core_sha,
                  "command_trace_enabled": args.trace_commands,
                  "source_sha256": sha(__file__), "window_source_sha256": source_sha,
                  "matches": reports, "total_presses": len(samples),
                  "physical_presses": len(samples) + len(excluded_transitions),
                  "excluded_unplayable_transitions": excluded_transitions,
                  "admitted_count": len(admitted), "response_count": len(responded),
                  "status_counts": dict(collections.Counter(row["status"] for row in samples)),
                  "input_admission_p95_ms": p95([row["input_admission_ms"] for row in admitted]),
                  "velocity_response_p95_ms": p95([row["velocity_response_ms"] for row in responded]),
                  "swap_after_response_p95_ms": p95([row["first_swap_after_response_ms"]
                                                       for row in responded]),
                  "render_blocking_p95_ms": p95([row["render_blocking_before_admission_ms"]
                                                  for row in admitted]),
                  "samples": samples}
        report["acceptance_passed"] = (len(responded) == len(samples) and
                                       report["velocity_response_p95_ms"] is not None and
                                       report["velocity_response_p95_ms"] <= 50)
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ("samples", "matches")}, sort_keys=True), flush=True)
        print(json.dumps({"artifact": str(output / "report.json"),
                          "artifact_sha256": sha(output / "report.json")}), flush=True)
    except BaseException as error:
        (output / "failure.json").write_text(json.dumps({"error_type": type(error).__name__,
                                                           "error": str(error),
                                                           "finished_matches": reports}, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
