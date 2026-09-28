#!/usr/bin/env python3
from pathlib import Path
import hashlib
import json
import os
import statistics
import sys
import time
import traceback

ROOT = Path("/root/work_space/football")
STAGE = Path(__file__).resolve().parent
REFERENCE = Path("/root/work_space/football-ecs-reference-build-20260928-a")
CURRENT = Path("/tmp/football-optimization-native")
sys.path.insert(0, str(ROOT / ".project/checks"))
import ecs_performance as ecs
import match_benchmark as benchmark

SHA = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
old = json.loads((STAGE / "reference-match.json").read_text())
new = json.loads((ROOT / ".project/optimization/benchmarks/match-1790585334093049240.json").read_text())
assert all(old["summary"][i]["final_hash"] == new["summary"][i]["final_hash"]
           for i in range(2))
engine_hashes = {
    "reference": SHA(REFERENCE / "libfootball_engine.so"),
    "current": SHA(CURRENT / "libfootball_engine.so"),
}
benchmark_hashes = {
    "reference": SHA(REFERENCE / "bin/engine_match_benchmark"),
    "current": SHA(CURRENT / "bin/engine_match_benchmark"),
}
assert engine_hashes["reference"] == old["binaries"]["engine"]
assert engine_hashes["current"] == new["binaries"]["engine"]
assert benchmark_hashes["reference"] == old["binaries"]["benchmark"]
assert benchmark_hashes["current"] == new["binaries"]["benchmark"]
reference_sources = old["sources"]
current_sources = new["sources"]
changed = [name for name in reference_sources if
           reference_sources[name] != current_sources[name]]
assert set(reference_sources) == set(current_sources)
assert set(changed) - {"engine/src/ecs/query.hpp"} == {
    name for name in changed if
    (ROOT / name).read_bytes().replace(b"\r\n", b"\n") ==
    (Path("/root/work_space/football-ecs-reference-20260928-a") / name)
        .read_bytes().replace(b"\r\n", b"\n")}

runs = []
cpu = min(os.sched_getaffinity(0))
started = time.time()
try:
    for repetition in range(15):
        for seed in ((42, 43) if repetition % 2 == 0 else (43, 42)):
            pair = {}
            order = ("reference", "current") if (repetition + seed) % 2 == 0 else ("current", "reference")
            for role in order:
                library = REFERENCE if role == "reference" else CURRENT
                result, profile, assertions = ecs.sample(
                    library / "bin/engine_match_benchmark", library, seed, cpu)
                assert profile is None
                result.update(role=role, repetition=repetition, assertions_checked=assertions)
                pair[role] = result
                runs.append(result)
            ecs.same_trajectory(pair["reference"], pair["current"])
            (STAGE / "paired-progress.json").write_text(json.dumps({
                "runs": runs, "pairs": len(runs) // 2}, indent=2) + "\n")
            print(json.dumps({"repetition": repetition, "seed": seed,
                              "cpu_ratio": pair["current"]["cpu_time"]["sum_ns"] /
                                           pair["reference"]["cpu_time"]["sum_ns"],
                              "wall_ratio": pair["current"]["steady"]["sum_ns"] /
                                            pair["reference"]["steady"]["sum_ns"]}), flush=True)
    comparisons = []
    for seed in (42, 43):
        refs = [x for x in runs if x["seed"] == seed and x["role"] == "reference"]
        curs = [x for x in runs if x["seed"] == seed and x["role"] == "current"]
        assert len(refs) == len(curs) == 15
        comparisons.append({"seed": seed,
            "cpu": ecs.paired_summary([(a["cpu_time"]["sum_ns"], b["cpu_time"]["sum_ns"])
                                       for a, b in zip(refs, curs)]),
            "wall": ecs.paired_summary([(a["steady"]["sum_ns"], b["steady"]["sum_ns"])
                                        for a, b in zip(refs, curs)]),
            "p99_ratio": statistics.median(b["steady"]["p99_ns"] /
                                           a["steady"]["p99_ns"]
                                           for a, b in zip(refs, curs))})
    assert engine_hashes == {"reference": SHA(REFERENCE / "libfootball_engine.so"),
                             "current": SHA(CURRENT / "libfootball_engine.so")}
    assert benchmark_hashes == {"reference": SHA(REFERENCE / "bin/engine_match_benchmark"),
                                "current": SHA(CURRENT / "bin/engine_match_benchmark")}
    (STAGE / "paired-report.json").write_text(json.dumps({
        "passed": True, "product_acceptance": False, "pairs_per_seed": 15,
        "same_trajectory": True, "changed_source_paths": changed,
        "engine_hashes": engine_hashes, "benchmark_hashes": benchmark_hashes,
        "comparisons": comparisons, "runs": runs,
        "started": started, "finished": time.time()}, indent=2) + "\n")
except BaseException as e:
    (STAGE / "paired-failure.json").write_text(json.dumps({
        "type": type(e).__name__, "message": str(e), "runs": len(runs),
        "started": started, "finished": time.time()}, indent=2) + "\n")
    traceback.print_exc()
    raise
