#!/usr/bin/env python3
"""Interleave immutable baseline and candidate matches; reject drift and unproven gains."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import time

import match_benchmark as benchmark
import ai_reachability_contract
from native_boundary import ROOT, require, run

# 2026-09-09: five-pair preflight gains are small relative to host variability.
# Fix a larger cohort before formal measurement, without changing thresholds.
PROCESS_PAIRS = 15


def paired_summary(pairs):
    require(len(pairs) >= 5, "At least five independent process pairs are required")
    ratios = [candidate / baseline for baseline, candidate in pairs]
    require(all(math.isfinite(value) and value > 0 for value in ratios), "Invalid paired measurement")
    logs = [math.log(value) for value in ratios]
    random_source = random.Random(20260909)
    means = sorted(math.exp(statistics.mean(random_source.choices(logs, k=len(logs)))) for _ in range(10000))
    return {"pairs": len(pairs), "ratios": ratios, "geometric_ratio": math.exp(statistics.mean(logs)),
            "bootstrap_95_lower": means[249], "bootstrap_95_upper": means[9749]}


def sample(binary, library, seed, cpu, profiler=None):
    environment = dict(os.environ, LD_LIBRARY_PATH=str(library))
    for name in ("LD_PRELOAD", "GFOOTBALL_DATA_DIR", "GFOOTBALL_FONT", "GFOOTBALL_USE_PBR"):
        environment.pop(name, None)
    if profiler:
        environment["LD_PRELOAD"] = str(profiler)
    output = subprocess.run([str(binary), str(seed), "200", "2000", str(cpu)], cwd=ROOT, env=environment,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    require(output.returncode == 0, f"Match failed: {output.stdout[-5000:]}")
    reports = [json.loads(line) for line in output.stdout.splitlines() if line.startswith("{")]
    normal = [report for report in reports if report.get("passed")]
    require(len(normal) == 1, "Missing or ambiguous native result")
    result = normal[0]
    assertions = benchmark.validate_run(result, seed, 200, 2000, cpu) + result["assertions"]
    profiles = [report for report in reports if report.get("hotspot_profile")]
    require(len(profiles) == (1 if profiler else 0), "Unexpected profiler state")
    return result, profiles[0] if profiler else None, assertions


def same_trajectory(left, right):
    for field in ("seed", "input_hash", "warm_hash", "final_hash", "state_checkpoints", "active_flags"):
        require(left[field] == right[field], f"Optimization changed trajectory: {field}")
    return 6


def profile_failures(pair):
    failures = []
    expected_names = {"frame", "players", "physics_sync", "collisions_cache", "full_cache"}
    buckets = {}
    for role in ("baseline", "candidate"):
        profile = pair[role]
        group = {item["name"]: item for item in profile["buckets"]}
        buckets[role] = group
        if set(group) != expected_names or len(profile["buckets"]) != len(expected_names):
            return [f"seed {pair['seed']}: incomplete {role} profile"]
        if (profile.get("hotspot_profile") is not True or profile["steps_seen"] != 4200
                or group["frame"]["calls"] != 2000 or group["full_cache"]["calls"] != 20000):
            failures.append(f"seed {pair['seed']}: wrong {role} profile interval")
        if any(item["calls"] <= 0 or item["ns"] <= 0 for item in group.values()):
            failures.append(f"seed {pair['seed']}: a {role} wrapper never ran")
    old, new = buckets["baseline"], buckets["candidate"]
    if any(old[name]["calls"] != new[name]["calls"] for name in expected_names):
        failures.append(f"seed {pair['seed']}: function coverage changed")
    if old["full_cache"]["allocations"] != 40000 or new["full_cache"]["allocations"] != 0:
        failures.append(f"seed {pair['seed']}: steady derived-cache allocations remain")
    if (new["frame"]["allocations"] >= old["frame"]["allocations"] or
            new["frame"]["bytes"] >= old["frame"]["bytes"]):
        failures.append(f"seed {pair['seed']}: real-match allocation cost did not decrease")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
    parser.add_argument("--tests-build", type=Path, default=Path("/tmp/football-optimization-query-tests"))
    args = parser.parse_args()
    require(args.cpu in os.sched_getaffinity(0), "Unavailable benchmark CPU")
    build = args.build.resolve()
    pointer_path = ROOT / ".project/optimization/benchmarks/baseline.json"
    pointer = json.loads(pointer_path.read_text())
    baseline_path = ROOT / pointer["source_artifact"]
    require(benchmark.file_hash(baseline_path) == pointer["artifact_sha256"], "Baseline evidence changed")
    baseline = json.loads(baseline_path.read_text())
    archive = Path(pointer["archive"])
    for role, path in (("engine", archive / "libfootball_engine.so"), ("benchmark", archive / "bin/engine_match_benchmark")):
        require(benchmark.file_hash(path) == pointer["binaries"][role], f"Immutable baseline {role} changed")
    for path, expected in baseline["sources"].items():
        if path.startswith(("engine/data/", "engine/fonts/")) or path in (
                "engine/tests/engine_match_benchmark.cpp", "engine/src/frame_sync/default_scenario.hpp"):
            require(benchmark.file_hash(ROOT / path) == expected, f"Comparison fixture changed: {path}")

    run(["cmake", "-S", "engine", "-B", build, "-DCMAKE_BUILD_TYPE=Release",
         "-DBUILD_PYTHON_BINDINGS=OFF", "-DFOOTBALL_ENABLE_SANITIZERS=OFF",
         f"-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / 'bin'}"])
    # 2026-09-09: validate the additional measured animation allocation hot path.
    # run(["cmake", "--build", build, "-j", "1", "--target", "engine_match_benchmark", "engine_hotspot_profile"])
    # 2026-09-13: the previous target list ended at engine_animation_query_contract.
    run(["cmake", "--build", build, "-j", "1", "--target", "engine_match_benchmark",
         "engine_hotspot_profile", "engine_animation_query_contract", "engine_ai_reachability_contract"])
    metadata_environment = dict(os.environ, LD_LIBRARY_PATH=str(build))
    metadata_environment.pop("LD_PRELOAD", None)
    reachability_contract = ai_reachability_contract.probe(build, metadata_environment)
    metadata_output = subprocess.check_output([str(build / "bin/engine_animation_query_contract")],
        cwd=ROOT, env=metadata_environment, text=True, timeout=60)
    metadata_reports = [json.loads(line) for line in metadata_output.splitlines() if line.startswith('{"passed"')]
    require(len(metadata_reports) == 1, "Missing/ambiguous metadata contract report")
    metadata_contract = metadata_reports[0]
    require(metadata_contract.get("passed") is True and metadata_contract.get("skipped") == 0 and
            metadata_contract.get("assertions", 0) >= 30000, "Incomplete metadata contract")
    compiler_cache = (build / "CMakeCache.txt").read_text()
    compiler = benchmark.re.search(r"^CMAKE_CXX_COMPILER:[^=]+=(.+)$", compiler_cache, benchmark.re.MULTILINE).group(1)
    compiler_version = run([compiler, "--version"], capture=True)
    require(compiler_version == baseline["compiler_version"], "Compiler differs from baseline")
    commands = json.loads((build / "compile_commands.json").read_text())
    for command in commands:
        flags = benchmark.shlex.split(command["command"])
        require("-O3" in flags and "-DNDEBUG" in flags and "-std=c++23" in flags and
                not any(flag.startswith("-fsanitize") or flag in ("-Ofast", "-ffast-math") for flag in flags),
                "Comparison requires the same release compiler contract")
    candidate = build / "bin/engine_match_benchmark"
    binaries = {"engine": benchmark.file_hash(build / "libfootball_engine.so"),
                "benchmark": benchmark.file_hash(candidate), "profiler": benchmark.file_hash(build / "libengine_hotspot_profile.so")}
    for directory in (archive, build):
        # 2026-09-09: use the same explicit loader selection as the measured process.
        # linkage = run(["ldd", directory / "bin/engine_match_benchmark"], capture=True)
        loader_environment = dict(os.environ, LD_LIBRARY_PATH=str(directory))
        loader_environment.pop("LD_PRELOAD", None)
        linkage = subprocess.check_output(["ldd", str(directory / "bin/engine_match_benchmark")],
                                          env=loader_environment, text=True)
        require(str(directory / "libfootball_engine.so") in linkage, "Match loads an unexpected engine")
    tests_build = args.tests_build.resolve()
    configure = ["cmake", "-S", "engine/tests", "-B", tests_build, "-DCMAKE_BUILD_TYPE=Debug",
                 f"-DCMAKE_CXX_COMPILER={compiler}", "-DENABLE_PCH=OFF", "-DENABLE_ASAN=ON", "-DENABLE_UBSAN=ON"]
    existing_gtest = Path("/tmp/football-review-20260909-tests/_deps/googletest-src")
    if existing_gtest.is_dir():
        configure.append(f"-DFETCHCONTENT_SOURCE_DIR_GOOGLETEST={existing_gtest}")
    run(configure)
    run(["cmake", "--build", tests_build, "-j", "1", "--target", "ecs_query_contract_test"])
    test_json = tests_build / "query-contract.json"
    test_output = subprocess.run([str(tests_build / "ecs_query_contract_test"), f"--gtest_output=json:{test_json}"],
        cwd=ROOT, env=dict(os.environ, ASAN_OPTIONS="halt_on_error=1:detect_leaks=1", UBSAN_OPTIONS="halt_on_error=1"),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    require(test_output.returncode == 0, f"Sanitized query contract failed: {test_output.stdout}")
    tests = json.loads(test_json.read_text())
    require(tests["tests"] >= 8 and tests["failures"] == 0 and tests["disabled"] == 0,
            "Missing or unsuccessful query contract tests")
    cases = [case for suite in tests["testsuites"] for case in suite["testsuite"]]
    require(len(cases) == tests["tests"] and
            all(case["status"] == "RUN" and case["result"] == "COMPLETED" for case in cases),
            "Query contract contains skipped or incomplete tests")
    sanitizer_libraries = run(["readelf", "-d", tests_build / "ecs_query_contract_test"], capture=True)
    require("libasan" in sanitizer_libraries and "libubsan" in sanitizer_libraries,
            "Query contract lacks required instrumentation")
    files = benchmark.source_manifest()
    source_identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    # 2026-09-09: include mandatory sanitized query boundaries in this task.
    # results, profiles, assertions = [], [], 0
    # 2026-09-09: native parser/reference assertions supplement the ECS boundaries.
    # results, profiles, assertions = [], [], tests["tests"]
    # 2026-09-13: previous count was tests["tests"] + metadata_contract["assertions"].
    results, profiles, assertions = [], [], (tests["tests"] + metadata_contract["assertions"] +
                                            reachability_contract["assertions"])
    # 2026-09-09: retain every sample from fifteen predefined process pairs.
    # for repetition in range(5):
    for repetition in range(PROCESS_PAIRS):
        for seed in (benchmark.SEEDS if repetition % 2 == 0 else tuple(reversed(benchmark.SEEDS))):
            pair = {}
            order = ("baseline", "candidate") if (repetition + seed) % 2 == 0 else ("candidate", "baseline")
            for role in order:
                library = archive if role == "baseline" else build
                result, _, checks = sample(library / "bin/engine_match_benchmark", library, seed, args.cpu)
                assertions += checks
                result.update(role=role, repetition=repetition)
                pair[role] = result
                results.append(result)
            assertions += same_trajectory(pair["baseline"], pair["candidate"])
            print(json.dumps({"seed": seed, "repetition": repetition,
                "cpu_ratio": pair["candidate"]["cpu_time"]["sum_ns"] / pair["baseline"]["cpu_time"]["sum_ns"],
                "wall_ratio": pair["candidate"]["steady"]["sum_ns"] / pair["baseline"]["steady"]["sum_ns"]}), flush=True)
    comparisons = []
    for seed in benchmark.SEEDS:
        previous = next(item for item in baseline["runs"] if item["seed"] == seed)
        groups = {role: [item for item in results if item["seed"] == seed and item["role"] == role]
                  for role in ("baseline", "candidate")}
        require(all(len(group) == PROCESS_PAIRS for group in groups.values()),
                "Incomplete predefined performance cohort")
        for result in groups["baseline"] + groups["candidate"]:
            assertions += same_trajectory(previous, result)
        item = {"seed": seed}
        for name, key in (("cpu", "cpu_time"), ("wall", "steady")):
            item[name] = paired_summary([(a[key]["sum_ns"], b[key]["sum_ns"])
                                        for a, b in zip(groups["baseline"], groups["candidate"])])
        item["p99_ratio"] = statistics.median(b["steady"]["p99_ns"] / a["steady"]["p99_ns"]
                                            for a, b in zip(groups["baseline"], groups["candidate"]))
        comparisons.append(item)
    # Independent instrumentation runs: counts explain the gain, their timings
    # never enter the uninstrumented comparisons above.
    for seed in benchmark.SEEDS:
        pair = {}
        for role, library in (("baseline", archive), ("candidate", build)):
            normal, profile, checks = sample(library / "bin/engine_match_benchmark", library, seed, args.cpu,
                                             profiler=build / "libengine_hotspot_profile.so")
            assertions += checks
            previous = next(item for item in baseline["runs"] if item["seed"] == seed)
            assertions += same_trajectory(previous, normal)
            require(profile["steps_seen"] == 4200 and profile["buckets"][0]["calls"] == 2000, "Wrong profile interval")
            pair[role] = profile
        profiles.append({"seed": seed, **pair})
    require(files == benchmark.source_manifest(), "Sources changed during comparison")
    require(binaries == {"engine": benchmark.file_hash(build / "libfootball_engine.so"),
                         "benchmark": benchmark.file_hash(candidate), "profiler": benchmark.file_hash(build / "libengine_hotspot_profile.so")},
            "Candidate binaries changed during comparison")
    artifact = ROOT / ".project/optimization/benchmarks" / f"ecs-comparison-{time.time_ns()}.json"
    failures = []
    for item in comparisons:
        if item["cpu"]["bootstrap_95_upper"] >= 1:
            failures.append(f"seed {item['seed']}: CPU improvement not established")
        if item["wall"]["geometric_ratio"] >= 1:
            failures.append(f"seed {item['seed']}: wall-time mean did not improve")
        if item["p99_ratio"] > 1.05:
            failures.append(f"seed {item['seed']}: median paired p99 regressed more than 5%")
    for pair in profiles:
        # 2026-09-09: zero allocations alone can hide a wrapper that never ran.
        # old = {item["name"]: item for item in pair["baseline"]["buckets"]}
        # new = {item["name"]: item for item in pair["candidate"]["buckets"]}
        # if old["full_cache"]["allocations"] != 40000 or new["full_cache"]["allocations"] != 0:
        #     failures.append(f"seed {pair['seed']}: steady derived-cache allocations remain")
        # if new["frame"]["allocations"] >= old["frame"]["allocations"]:
        #     failures.append(f"seed {pair['seed']}: real-match allocation count did not decrease")
        failures.extend(profile_failures(pair))
    assertions += 5 * len(comparisons)
    payload = {"format": 1, "passed": not failures, "failures": failures, "assertions": assertions, "skipped": 0,
               "source_identity": source_identity, "sources": files, "binaries": binaries,
               "baseline": pointer, "compiler_version": compiler_version, "compile_commands": commands,
               "machine": benchmark.machine_identity(args.cpu), "comparisons": comparisons,
               "profile_scope": "inclusive main benchmark thread malloc/calloc/realloc calls; separate instrumented runs",
               "query_contract": tests,
               "animation_metadata_contract": metadata_contract,
               "ai_reachability_contract": reachability_contract,
               "planned_pairs_per_seed": PROCESS_PAIRS,
               "statistic": "paired log CPU mean; 10000 deterministic bootstrap resamples, percentile 95% interval",
               "results": results, "profiles": profiles}
    artifact.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"passed": not failures, "assertions": assertions, "skipped": 0, "failures": failures,
                      "artifact": str(artifact.relative_to(ROOT)), "artifact_sha256": benchmark.file_hash(artifact),
                      "comparisons": comparisons}), flush=True)
    require(not failures, "Performance gain is unproven; retain evidence and continue optimization")


if __name__ == "__main__":
    main()
