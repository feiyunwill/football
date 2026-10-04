#!/usr/bin/env python3
"""Freeze a current-gameplay ECS reference with only the recorded optimizations reversed."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".project/checks"))
import ecs_performance as ecs  # noqa: E402
import match_benchmark as benchmark  # noqa: E402

ROLLBACK_FILES = {
    "engine/src/base/math/vector3.hpp",
    "engine/src/onthepitch/player/humanoid/humanoid.cpp",
    "engine/src/onthepitch/player/humanoid/humanoidbase.cpp",
    "engine/src/onthepitch/player/humanoid/humanoidbase.hpp",
}


def checked(args, cwd=ROOT, env=None):
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True,
                          check=True).stdout


def digest(data):
    return hashlib.sha256(data).hexdigest()


def packed_json(value):
    raw = (json.dumps(value, indent=2) + "\n").encode()
    return raw, gzip.compress(raw, compresslevel=9, mtime=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--candidate-build", type=Path, required=True)
    args = parser.parse_args()
    worktree, build, candidate = (path.resolve() for path in
                                  (args.worktree, args.build, args.candidate_build))
    parent_path = ROOT / ".project/optimization/baselines/ecs_v9.json"
    parent = json.loads(parent_path.read_text())
    patch = ROOT / ".project/optimization/baselines/ecs_v10_perf_rollback.patch"
    if not patch.is_file():
        raise RuntimeError("Current-gameplay ECS rollback patch is missing")
    source_commit = checked(["git", "rev-parse", "HEAD"]).strip()
    if checked(["git", "rev-parse", "HEAD"], worktree).strip() != source_commit:
        raise RuntimeError("Reference worktree is not based on the current commit")
    if checked(["git", "diff", "--name-only"], worktree).splitlines() != sorted(ROLLBACK_FILES):
        raise RuntimeError("Reference worktree has changes beyond the ECS rollback")
    if checked(["git", "status", "--porcelain", "--untracked-files=normal"], worktree).count("\n") != 4:
        raise RuntimeError("Reference worktree has untracked or staged files")
    checked(["git", "apply", "-R", "--check", str(patch)], worktree)
    if digest(checked(["git", "diff", "--binary"], worktree).encode()) != benchmark.file_hash(patch):
        raise RuntimeError("Reference edits differ from the recorded ECS rollback")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "engine/src"],
                      cwd=ROOT).returncode != 0:
        raise RuntimeError("Current product engine differs from the pinned commit")

    engine = build / "libfootball_engine.so"
    executable = build / "bin/engine_match_benchmark"
    current = candidate / "bin/engine_match_benchmark"
    for path in (engine, executable, current, candidate / "libfootball_engine.so"):
        if not path.is_file():
            raise RuntimeError(f"Missing measured binary: {path}")
    linkage = checked(["ldd", str(executable)],
                      env=dict(os.environ, LD_LIBRARY_PATH=str(build)))
    if str(engine) not in linkage:
        raise RuntimeError("Reference benchmark loads a different engine")
    cache = (build / "CMakeCache.txt").read_text()
    compiler = re.search(r"^CMAKE_CXX_COMPILER:[^=]+=(.+)$", cache, re.MULTILINE)
    if not compiler:
        raise RuntimeError("Missing reference C++ compiler")
    compiler_path = compiler.group(1)
    compiler_version = checked([compiler_path, "--version"])
    commands = json.loads((build / "compile_commands.json").read_text())
    if len(commands) < 100 or any("-O3" not in row["command"] or
                                  "-DNDEBUG" not in row["command"] for row in commands):
        raise RuntimeError("Reference lacks a full Release compilation database")

    cpu = min(os.sched_getaffinity(0))
    baseline_runs, validation_runs = [], []
    for seed in benchmark.SEEDS:
        first, _, _ = ecs.sample(executable, build, seed, cpu)
        repeat, _, _ = ecs.sample(executable, build, seed, cpu)
        new, _, _ = ecs.sample(current, candidate, seed, cpu)
        ecs.same_trajectory(first, repeat)
        ecs.same_trajectory(first, new)
        baseline_runs.append(first)
        validation_runs.append({"seed": seed, "baseline_repeat": repeat,
                                "candidate": new})
        print(json.dumps({"seed": seed, "warm_hash": first["warm_hash"],
                          "final_hash": first["final_hash"],
                          "trajectory_equal": True}), flush=True)
    profiler = candidate / "libengine_hotspot_profile.so"
    profiles = []
    for seed in benchmark.SEEDS:
        pair = {}
        for role, directory in (("baseline", build), ("candidate", candidate)):
            _, profile, _ = ecs.sample(directory / "bin/engine_match_benchmark",
                                       directory, seed, cpu, profiler)
            pair[role] = profile
        failures = ecs.profile_failures({"seed": seed, **pair})
        if failures:
            raise RuntimeError(f"Allocation preflight failed: {failures}")
        profiles.append({"seed": seed, **pair})

    original_root = benchmark.ROOT
    try:
        benchmark.ROOT = worktree
        sources = benchmark.source_manifest()
    finally:
        benchmark.ROOT = original_root
    source_identity = digest(json.dumps(sources, sort_keys=True).encode())
    binaries = {"engine": digest(engine.read_bytes()),
                "benchmark": digest(executable.read_bytes())}
    artifact = {
        "format": 10, "source_commit": source_commit,
        "source_identity": source_identity, "sources": sources,
        "binaries": binaries,
        "compile_commands": [f"cmake -S {worktree / 'engine'} -B {build} "
                             "-DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=OFF "
                             "-DFOOTBALL_ENABLE_SANITIZERS=OFF",
                             f"cmake --build {build} -j 1 --target engine_match_benchmark"],
        "compiler_path": compiler_path, "compiler_version": compiler_version,
        "machine": benchmark.machine_identity(cpu),
        "environment": {name: None for name in
                        ("LD_PRELOAD", "GFOOTBALL_DATA_DIR", "GFOOTBALL_FONT",
                         "GFOOTBALL_USE_PBR")},
        "measurement_contract": parent["measurement_contract"],
        "summary": benchmark.summarize(baseline_runs), "runs": baseline_runs,
    }
    validation = {"format": 1, "source_commit": source_commit,
                  "source_identity": source_identity, "cpu": cpu,
                  "runs": validation_runs, "profiles": profiles,
                  "rollback_patch_sha256": benchmark.file_hash(patch)}
    raw, packed = packed_json(artifact)
    _, validation_packed = packed_json(validation)
    base = ROOT / ".project/optimization/baselines"
    evidence = ROOT / ".project/optimization/evidence"
    paths = {
        "engine": base / "ecs_v10_engine.so.gz",
        "benchmark": base / "ecs_v10_match_benchmark.gz",
        "artifact": evidence / "ecs_pass_buffer_preperf_reference_20261004.json.gz",
        "validation": evidence / "ecs_v10_preflight_20261004.json.gz",
        "manifest": base / "ecs_v10.json",
    }
    if any(path.exists() for path in paths.values()):
        raise RuntimeError("Versioned ECS v10 reference already exists")
    binary_entries = {}
    for role, path in (("engine", engine), ("benchmark", executable)):
        data = path.read_bytes()
        compressed = gzip.compress(data, compresslevel=9, mtime=0)
        destination = paths[role]
        destination.write_bytes(compressed)
        binary_entries[role] = {
            "path": destination.relative_to(ROOT).as_posix(),
            "compressed_sha256": digest(compressed), "sha256": digest(data),
            "compressed_bytes": len(compressed), "bytes": len(data),
        }
    paths["artifact"].write_bytes(packed)
    paths["validation"].write_bytes(validation_packed)
    manifest = {
        "format": 10, "id": "ecs-pass-buffer-current-gameplay-pre-selection-scratch-and-vector-length-20261004",
        "source_commit": source_commit,
        "semantic_patch": patch.relative_to(ROOT).as_posix(),
        "semantic_patch_sha256": benchmark.file_hash(patch),
        "source_identity": source_identity,
        "source_artifact": paths["artifact"].relative_to(ROOT).as_posix(),
        "artifact_sha256": digest(packed),
        "artifact_uncompressed_sha256": digest(raw),
        "validation_artifact": paths["validation"].relative_to(ROOT).as_posix(),
        "validation_artifact_sha256": digest(validation_packed),
        "measurement_contract": parent["measurement_contract"],
        "binaries": binary_entries,
        "derived_from_baseline_v9_sha256": benchmark.file_hash(parent_path),
        "generator_sha256": benchmark.file_hash(Path(__file__)),
    }
    paths["manifest"].write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"passed": True, "manifest": manifest["id"],
                      "manifest_sha256": benchmark.file_hash(paths["manifest"]),
                      "trajectory_seeds": list(benchmark.SEEDS),
                      "allocation_profiles": len(profiles)}))


if __name__ == "__main__":
    main()
