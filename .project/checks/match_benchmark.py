#!/usr/bin/env python3
"""Measure and retain reproducible real-engine performance without optimizing it."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import statistics
import subprocess
import time

from native_boundary import ROOT, require, run

SEEDS = (42, 43)
WARMUP = 200
SAMPLES = 2000
REPETITIONS = 5
HASH = re.compile(r"[0-9a-f]{16}")


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def distribution(values):
    result = {"count": len(values)}
    if values:
        ordered = sorted(values)
        result.update(sum_ns=sum(values), max_ns=max(values))
        for quantile in (50, 95, 99):
            result[f"p{quantile}_ns"] = ordered[math.ceil(len(values) * quantile / 100) - 1]
    return result


def validate_run(result, seed, warmup, samples, cpu):
    """Recompute summaries from raw samples; never trust a reported p99 alone."""
    assertions = 0

    def check(condition, message):
        nonlocal assertions
        assertions += 1
        require(condition, message)

    check(result.get("passed") is True and result.get("skipped") == 0 and
          type(result.get("assertions")) is int and result["assertions"] >= 14, "Incomplete native benchmark")
    for key, expected in (("format", 1), ("seed", seed), ("warmup_frames", warmup),
                          ("measured_frames", samples), ("cpu", cpu), ("players", [11, 11]),
                          ("slots", [2, 2]), ("physics_ticks_per_frame", 10),
                          ("logical_frame_budget_ns", 100_000_000), ("snapshot_replay", True)):
        check(result.get(key) == expected, f"Unexpected benchmark contract: {key}")
    for key, count in (("raw_warmup_ns", warmup), ("raw_frame_ns", samples), ("raw_cpu_ns", samples)):
        values = result.get(key, [])
        check(len(values) == count and all(type(value) is int and value > 0 for value in values),
              f"Invalid raw samples: {key}")
    flags = result.get("active_flags", [])
    check(len(flags) == samples and all(type(value) is int and value in (0, 1) for value in flags), "Invalid activity flags")
    check(sum(flags) >= samples // 4, "Insufficient actual in-play measurements")
    active = [value for value, flag in zip(result["raw_frame_ns"], flags) if flag]
    stopped = [value for value, flag in zip(result["raw_frame_ns"], flags) if not flag]
    for key, values in (("warmup", result["raw_warmup_ns"]), ("steady", result["raw_frame_ns"]),
                        ("cpu_time", result["raw_cpu_ns"]), ("active", active), ("stopped", stopped)):
        check(result.get(key) == distribution(values), f"Summary differs from raw measurements: {key}")
    for key in ("input_hash", "warm_hash", "final_hash"):
        check(isinstance(result.get(key), str) and HASH.fullmatch(result[key]), f"Missing state/input identity: {key}")
    checkpoints = result.get("state_checkpoints", [])
    expected_checkpoints = math.ceil(samples / 100) + 1
    check(len(checkpoints) == expected_checkpoints and all(isinstance(value, str) and HASH.fullmatch(value)
          for value in checkpoints), "Missing trajectory checkpoints")
    check(checkpoints[0] == result["warm_hash"] and checkpoints[-1] == result["final_hash"], "Trajectory endpoints disagree")
    check(len(set(checkpoints)) > 1, "Stationary state was reported as simulation")
    rss = result.get("rss_checkpoints_bytes", [])
    check(len(rss) == expected_checkpoints and all(type(value) is int and value > 0 for value in rss),
          "Missing RSS checkpoints")
    for key in ("initial_rss_bytes", "startup_rss_bytes", "warm_rss_bytes", "final_rss_bytes",
                "closed_rss_bytes", "peak_rss_bytes", "startup_ns", "close_ns", "loop_wall_ns", "diagnostics_ns"):
        check(type(result.get(key)) is int and result[key] > 0, f"Missing measured lifecycle field: {key}")
    check(result["loop_wall_ns"] >= sum(result["raw_frame_ns"]) + result["diagnostics_ns"],
          "Timed diagnostics overlap the reported frame intervals")
    check(result.get("actual_end_ms", 0) >= result.get("actual_start_ms", 0) + samples * 100,
          "Physical timeline did not advance")
    check(result.get("kicked_history_frames", 0) > 0, "Fixture produced no intentional kick")
    return assertions


def validate_repeats(results, repetitions):
    require(len(results) == len(SEEDS) * repetitions, "Missing independent benchmark processes")
    for seed in SEEDS:
        group = [item for item in results if item["seed"] == seed]
        require(len(group) == repetitions, f"Wrong repetition count for seed {seed}")
        for key in ("input_hash", "warm_hash", "final_hash", "state_checkpoints", "active_flags"):
            require(all(item[key] == group[0][key] for item in group), f"Nondeterministic benchmark {key}, seed {seed}")
    return len(SEEDS) * 6 + 1


def source_manifest():
    manifest = json.loads((ROOT / ".project/optimization/program.json").read_text())
    check = next(item for item in manifest["checks"] if item["id"] == "match_benchmark")
    files = set()
    for pattern in check["sources"]:
        matches = [path for path in ROOT.glob(pattern) if path.is_file()]
        require(matches, f"Empty source identity scope: {pattern}")
        files.update(matches)
    hashes = {}
    for path in sorted(files):
        require(path.resolve().is_relative_to(ROOT), f"Source identity escapes repository: {path}")
        hashes[path.relative_to(ROOT).as_posix()] = file_hash(path)
    return hashes


def machine_identity(cpu):
    def read_optional(path):
        candidate = Path(path)
        return candidate.read_text().strip() if candidate.is_file() else None
    return {"platform": platform.platform(), "machine": platform.machine(), "cpu": cpu,
            "parent_cpu_affinity": sorted(os.sched_getaffinity(0)),
            "cpuinfo": Path("/proc/cpuinfo").read_text(),
            "meminfo": Path("/proc/meminfo").read_text(),
            "cgroup": Path("/proc/self/cgroup").read_text(),
            "cgroup_cpu_max": read_optional("/sys/fs/cgroup/cpu.max"),
            "cgroup_memory_max": read_optional("/sys/fs/cgroup/memory.max"),
            "governor": read_optional(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor"),
            "topology": {key: read_optional(f"/sys/devices/system/cpu/cpu{cpu}/topology/{key}")
                         for key in ("physical_package_id", "core_id", "thread_siblings_list")}}


def summarize(results):
    summaries = []
    for seed in SEEDS:
        group = [item for item in results if item["seed"] == seed]
        summaries.append({"seed": seed, "processes": len(group), "samples": sum(item["measured_frames"] for item in group),
                          "startup_p50_ms": statistics.median(item["startup_ns"] for item in group) / 1e6,
                          "steady": distribution([value for item in group for value in item["raw_frame_ns"]]),
                          "per_process_p99_ns": [item["steady"]["p99_ns"] for item in group],
                          "active_frames": sum(item["active"]["count"] for item in group),
                          "stopped_frames": sum(item["stopped"]["count"] for item in group),
                          "rss_max_observed_bytes": max(max(item["rss_checkpoints_bytes"]) for item in group),
                          "rss_max_growth_bytes": max(item["rss_checkpoints_bytes"][-1] - item["rss_checkpoints_bytes"][0] for item in group),
                          "final_hash": group[0]["final_hash"], "input_hash": group[0]["input_hash"]})
    return summaries


def capture(binary, environment, cpu, repetitions=REPETITIONS, warmup=WARMUP, samples=SAMPLES):
    results, assertions = [], 0
    for repetition in range(repetitions):
        # Alternate seeds to avoid confounding the second seed with a hotter CPU.
        order = SEEDS if repetition % 2 == 0 else tuple(reversed(SEEDS))
        for seed in order:
            argv = [str(binary), str(seed), str(warmup), str(samples), str(cpu)]
            started = time.perf_counter_ns()
            output = subprocess.run(argv, cwd=ROOT, env=environment, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=180)
            launch_ns = time.perf_counter_ns() - started
            require(output.returncode == 0, f"Benchmark exited {output.returncode}: {output.stdout[-6000:]}")
            reports = [json.loads(line) for line in output.stdout.splitlines() if line.startswith('{"passed"')]
            require(len(reports) == 1, "Missing/ambiguous native benchmark result")
            result = reports[0]
            assertions += validate_run(result, seed, warmup, samples, cpu) + result["assertions"]
            result.update(repetition=repetition, argv=argv, process_wall_ns=launch_ns)
            results.append(result)
            print(json.dumps({"seed": seed, "repetition": repetition, "startup_ms": result["startup_ns"] / 1e6,
                              "steady_p50_ms": result["steady"]["p50_ns"] / 1e6,
                              "steady_p95_ms": result["steady"]["p95_ns"] / 1e6,
                              "steady_p99_ms": result["steady"]["p99_ns"] / 1e6,
                              "hash": result["final_hash"]}), flush=True)
    assertions += validate_repeats(results, repetitions)
    return results, assertions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
    args = parser.parse_args()
    require(args.cpu in os.sched_getaffinity(0), "Benchmark CPU is unavailable")
    build = args.build.resolve()
    run(["cmake", "-S", "engine", "-B", build, "-DCMAKE_BUILD_TYPE=Release",
         "-DFOOTBALL_ENABLE_SANITIZERS=OFF", "-DBUILD_PYTHON_BINDINGS=OFF",
         f"-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / 'bin'}"])
    commands = json.loads((build / "compile_commands.json").read_text())
    cache = (build / "CMakeCache.txt").read_text()
    compiler_match = re.search(r"^CMAKE_CXX_COMPILER:[^=]+=(.+)$", cache, re.MULTILINE)
    require(compiler_match is not None, "Missing actual C++ compiler identity")
    compiler = compiler_match.group(1)
    compiler_version = run([compiler, "--version"], capture=True)

    require(len(commands) >= 100, "Missing full engine compiler configuration")
    for command in commands:
        flags = shlex.split(command["command"])
        require("-O3" in flags and "-DNDEBUG" in flags and "-std=c++23" in flags and
                not any(flag.startswith("-fsanitize") or flag in ("-Ofast", "-ffast-math") for flag in flags),
                f"Invalid benchmark compilation flags: {command['file']}")
    run(["cmake", "--build", build, "-j", "1", "--target", "engine_match_benchmark"])
    binary = build / "bin/engine_match_benchmark"
    engine = build / "libfootball_engine.so"
    dynamic = run(["readelf", "-d", engine], capture=True)
    require("libasan" not in dynamic and "libubsan" not in dynamic and "libpython" not in dynamic,
            "Benchmark is linked to an instrumentation/Python runtime")
    environment = dict(os.environ)
    for name in ("LD_PRELOAD", "GFOOTBALL_DATA_DIR", "GFOOTBALL_FONT", "GFOOTBALL_USE_PBR"):
        environment.pop(name, None)
    # 2026-09-09: bind the measured process to the library whose bytes we hash.
    environment["LD_LIBRARY_PATH"] = str(build)
    files = source_manifest()
    file_identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    binaries = {"engine": file_hash(engine), "benchmark": file_hash(binary)}
    machine = machine_identity(args.cpu)
    results, assertions = capture(binary, environment, args.cpu)
    require(files == source_manifest() and binaries == {"engine": file_hash(engine), "benchmark": file_hash(binary)},
            "Sources or binaries changed while benchmarking")
    artifact = ROOT / ".project/optimization/benchmarks" / f"match-{time.time_ns()}.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    # 2026-09-09: c++ --version could describe a different compiler than custom CXX.
    # Previous field: "compiler_version": run(["c++", "--version"], capture=True)
    payload = {"format": 1, "source_identity": file_identity, "sources": files, "binaries": binaries,
               "compile_commands": commands, "compiler_path": compiler, "compiler_version": compiler_version,
               "machine": machine, "environment": {name: environment.get(name) for name in
                   ("LD_LIBRARY_PATH", "LD_PRELOAD", "MALLOC_ARENA_MAX", "GLIBC_TUNABLES", "GFOOTBALL_DATA_DIR", "GFOOTBALL_FONT")},
               "measurement_contract": {"clock": "steady_clock nanoseconds", "cpu_clock": "CLOCK_PROCESS_CPUTIME_ID",
                   "rss": "/proc/self/smaps_rollup Rss (sampled outside frame interval)",
                   "peak_rss": "getrusage ru_maxrss (separate kernel high-water accounting, includes replay)",
                   "startup": "start_game in each fresh process; filesystem cache is not flushed",
                   "steady": "StepWithInput only; precomputed input and checkpoint diagnostics excluded",
                   "quantile": "nearest rank", "warmup_frames": WARMUP, "measured_frames": SAMPLES,
                   "repetitions_per_seed": REPETITIONS}, "summary": summary, "runs": results}
    artifact.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"passed": True, "assertions": assertions, "skipped": 0,
                      "artifact": str(artifact.relative_to(ROOT)), "artifact_sha256": file_hash(artifact),
                      "source_identity": file_identity, "runs": len(results), "summary": summary}))


if __name__ == "__main__":
    main()
