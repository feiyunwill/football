#!/usr/bin/env python3
"""Run deterministic, uninstrumented full-match pairs for two engine builds.

The build directories must each contain libfootball_engine.so and
bin/engine_match_benchmark. Build the reference from the documented commit
before changing source, then build the candidate separately.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".project/checks"))
import ecs_performance as ecs


def hashes(build):
    return {
        "engine": hashlib.sha256((build / "libfootball_engine.so").read_bytes()).hexdigest(),
        "benchmark": hashlib.sha256((build / "bin/engine_match_benchmark").read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=15)
    parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
    args = parser.parse_args()
    assert args.pairs > 0
    assert args.cpu in os.sched_getaffinity(0)
    builds = {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}
    initial_hashes = {role: hashes(build) for role, build in builds.items()}
    runs = []
    started = time.time()
    for repetition in range(args.pairs):
        seeds = (42, 43) if repetition % 2 == 0 else (43, 42)
        for seed in seeds:
            pair = {}
            order = (("baseline", "candidate") if (repetition + seed) % 2 == 0
                     else ("candidate", "baseline"))
            for role in order:
                build = builds[role]
                result, profile, assertions = ecs.sample(
                    build / "bin/engine_match_benchmark", build, seed, args.cpu)
                assert profile is None
                result.update(role=role, repetition=repetition,
                              assertions_checked=assertions)
                pair[role] = result
                runs.append(result)
            ecs.same_trajectory(pair["baseline"], pair["candidate"])
            args.output.write_text(json.dumps({
                "complete": False, "started": started, "runs": runs}, indent=2) + "\n")
            print(json.dumps({
                "repetition": repetition, "seed": seed,
                "cpu_ratio": (pair["candidate"]["cpu_time"]["sum_ns"] /
                              pair["baseline"]["cpu_time"]["sum_ns"]),
                "wall_ratio": (pair["candidate"]["steady"]["sum_ns"] /
                               pair["baseline"]["steady"]["sum_ns"]),
            }), flush=True)
    comparisons = []
    for seed in (42, 43):
        old = [r for r in runs if r["seed"] == seed and r["role"] == "baseline"]
        new = [r for r in runs if r["seed"] == seed and r["role"] == "candidate"]
        assert len(old) == len(new) == args.pairs
        comparisons.append({
            "seed": seed,
            "cpu": ecs.paired_summary([
                (a["cpu_time"]["sum_ns"], b["cpu_time"]["sum_ns"])
                for a, b in zip(old, new)]),
            "wall": ecs.paired_summary([
                (a["steady"]["sum_ns"], b["steady"]["sum_ns"])
                for a, b in zip(old, new)]),
            "p99_ratio": statistics.median(
                b["steady"]["p99_ns"] / a["steady"]["p99_ns"]
                for a, b in zip(old, new)),
        })
    assert initial_hashes == {role: hashes(build) for role, build in builds.items()}
    args.output.write_text(json.dumps({
        "complete": True, "product_acceptance": False,
        "cpu": args.cpu, "hashes": initial_hashes,
        "comparisons": comparisons, "runs": runs,
        "started": started, "finished": time.time()}, indent=2) + "\n")
    print(json.dumps({"comparisons": comparisons}), flush=True)


if __name__ == "__main__":
    main()
