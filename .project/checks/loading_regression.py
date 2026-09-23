#!/usr/bin/env python3
"""Exercise prepared-state, actual resource unwind and authenticated loading transport."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from native_boundary import ROOT, require, run

TARGETS = (
    "engine_prepared_lifecycle_contract", "engine_tracker_owner_contract",
    "engine_loading_cancellation_contract", "engine_loading_seat_contract",
    "engine_loading_tcp_contract", "engine_loading_client_drain_contract",
    "engine_loading_udp_client_drain_contract",
)
CHECKPOINTS = (
    ("reset.begin", 1), ("match.begin", 1), ("animations.template", 2),
    ("animations.generate", 17), ("animations.prepare-generated", 5),
    ("animations.file", 3), ("animations.cache", 4), ("team.player", 2),
    ("match.players", 1), ("match.stadium", 1), ("match.finalized", 1),
    ("reset.controllers", 1), ("reset.cache", 1), ("reset.pages", 1),
    ("reset.match-data", 1), ("reset.loading-page", 1),
    ("loading.background.create", 1), ("loading.background.load", 1),
    ("loading.background.ready", 1), ("loading.caption.left", 1),
    ("loading.logo.left.create", 1), ("loading.logo.left.load", 1),
    ("loading.caption.right", 1), ("loading.logo.right.create", 1),
    ("loading.logo.right.load", 1), ("loading.finalize", 1),
)

def probe(build, environment):
    environment = dict(environment, EXPECTED_CORE_PATH=str(build / "libfootball_engine.so"))
    results = {}
    def check(name, arguments=(), expected=None):
        binary = build / "bin" / name
        print("Running loading contract: " + " ".join(map(str, [binary, *arguments])), flush=True)
        completed = subprocess.run([str(binary), *map(str, arguments)], cwd=ROOT, env=environment,
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        print(completed.stdout, flush=True)
        require(completed.returncode == 0, f"Loading contract failed: {name} ({completed.returncode})")
        require(not any(marker in completed.stdout for marker in
                        ("runtime error:", "ERROR: AddressSanitizer", "ERROR: LeakSanitizer")),
                "Sanitizer diagnostic in loading contract")
        reports = [json.loads(line) for line in completed.stdout.splitlines()
                   if line.startswith('{"passed"')]
        require(len(reports) == 1, "Missing or ambiguous loading result")
        result = reports[0]
        require(result.get("passed") is True and result.get("skipped") == 0, "Incomplete loading result")
        require(all(result.get(key) == value for key, value in (expected or {}).items()),
                "Loading contract coverage changed")
        return result
    results["prepared"] = check(TARGETS[0], ["contract"],
                               {"prepared_operations": 19, "frames": 20, "actual_gameenv": True})
    results["tracker"] = check(TARGETS[1], expected={"paired_tracker": True, "workers": 2})
    for phase, repetition in CHECKPOINTS:
        results[phase] = check(TARGETS[2], [phase, repetition],
                               {"actual_gameenv": True, "cancelled": True})
    # 2026-09-15: keep all 12 ownership cases and add two actual TCP terminal-stream cases.
    # results["seat"] = check(TARGETS[3], expected={"checks": 12, "real_tcp": True, "actual_gameenv": False})
    results["seat"] = check(TARGETS[3], expected={"checks": 14, "ownership_checks": 12,
                                                "stream_terminal_checks": 2,
                                                "real_tcp": True, "actual_gameenv": False})
    results["legacy_loading"] = check(TARGETS[4],
                                     expected={"checks": 11, "real_tcp": True, "actual_gameenv": False})
    for key, target, transport in (("client_drain", TARGETS[5], "TCP"),
                                    ("udp_client_drain", TARGETS[6], "UDP")):
        results[key] = check(target, expected={"checks": 5, "assertions": 35,
                             "transport": transport, "actual_client": True,
                             "actual_gameenv": True})
        require(0 <= results[key]["maximum_cancel_seconds"] < .25,
                f"Actual {transport} client cancellation drain exceeds 250ms or is invalid")
    return {"passed": True, "assertions": sum(row.get("assertions", 0) for row in results.values()),
            "checks": len(results), "skipped": 0, "cancellation_checkpoints": len(CHECKPOINTS),
            "prepared_operations": 19, "actual_client_drain_cases": 10, "socket_ownership_cases": 12,
            "legacy_loading_cases": 11, "stream_terminal_cases": 2, "results": results}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-sanitized"))
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    build = args.build.resolve()
    if not args.skip_build:
        run(["cmake", "--build", build, "-j", "1", "--target", *TARGETS])
    environment = dict(os.environ)
    for key in ("DISPLAY", "LD_PRELOAD", "SDL_VIDEODRIVER", "GFOOTBALL_FONT"):
        environment.pop(key, None)
    environment.update(GFOOTBALL_DATA_DIR=str(ROOT / "engine/data"),
                       LD_LIBRARY_PATH=str(build), ASAN_OPTIONS="halt_on_error=1:detect_leaks=1:quarantine_size_mb=16",
                       UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1", LSAN_OPTIONS="exitcode=23")
    print(json.dumps(probe(build, environment)))

if __name__ == "__main__":
    main()
