"""Run exact differential arrival-time cases against the frozen pre-optimization body."""
import hashlib
import json
import os
import subprocess

from native_boundary import ROOT, require

REFERENCE = ROOT / "engine/tests/fixtures/ai_time_needed_20260913.inc"
REFERENCE_SHA256 = "b3cae7d462cf8e894ba12c9e5ccf04f22e69b8b4a2c5c7e6227a901a3aafb923"


def probe(build, environment=None):
    require(hashlib.sha256(REFERENCE.read_bytes()).hexdigest() == REFERENCE_SHA256,
            "Frozen arrival-time reference changed")
    environment = dict(os.environ if environment is None else environment,
                       LD_LIBRARY_PATH=str(build))
    environment.pop("LD_PRELOAD", None)
    command = [str(build / "bin/engine_ai_reachability_contract")]
    print("Running arrival-time differential contract: " + command[0], flush=True)
    output = subprocess.run(command, cwd=ROOT, env=environment, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    print(output.stdout, flush=True)
    require(output.returncode == 0, "Arrival-time differential contract failed")
    require(not any(message in output.stdout for message in
                    ("runtime error:", "ERROR: AddressSanitizer", "ERROR: LeakSanitizer")),
            "Arrival-time sanitizer diagnostic")
    reports = [json.loads(line) for line in output.stdout.splitlines()
               if line.startswith('{"passed"')]
    require(len(reports) == 1, "Missing or ambiguous arrival-time contract report")
    result = reports[0]
    require(result.get("passed") is True and result.get("skipped") == 0 and
            result.get("cases") == 216640 and result.get("assertions") == 1555846 and
            result.get("cached_cases") == 561280 and
            0 < result.get("trajectory_bytes", 0) <= 1536 and
            all(result.get(key, 0) > 0 for key in
                ("zero_results", "fast_distance_cases", "finite_timeout_cases")),
            "Incomplete arrival-time differential contract")
    return dict(result, reference_sha256=REFERENCE_SHA256)
