#!/usr/bin/env python3
"""Verify real tactical observations, bounded decisions, and TCP/UDP takeover."""
from pathlib import Path
import argparse
import json
import os
import signal
import sys
import time

import match_benchmark as benchmark
import performance_regression as runner
# 2026-09-14: use the complete canonical product set in every integration build.
# from native_boundary import ROOT, require
from native_boundary import ROOT, TARGETS, require


CONTRACTS = {
    "engine_ai_tactics_contract": (7288, {"symmetry_cases": 600}),
    "engine_ai_tactics_roles_contract": (3601, {"role_mirror_cases": 1800, "failed": 0}),
    "engine_ai_tactical_state_contract": (
        27618, {"frames": 960, "actual_gameenv": True, "nonzero_actors": 3513, "restarts": 331}),
    "engine_ai_touch_contract": (
        586, {"seeds": 3, "ball_control_assets": 270, "quiet_idle": 24, "actual_gameenv": True}),
}


def parsed(raw, minimum, expected):
    reports = [json.loads(line) for line in raw.splitlines()
               if line.startswith('{"passed"')]
    require(len(reports) == 1, "Missing or ambiguous tactical report")
    result = reports[0]
    require(result.get("passed") is True and result.get("skipped") == 0 and
            result.get("assertions", 0) >= minimum, "Incomplete tactical cohort")
    require(all(result.get(key) == value for key, value in expected.items()),
            "Tactical coverage fields differ")
    require(not any(word in raw for word in
                    ("runtime error:", "ERROR: AddressSanitizer", "ERROR: LeakSanitizer")),
            "Tactical sanitizer diagnostic")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("decisions", "integration"), required=True)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    parser.add_argument("--sanitized-build", type=Path,
                        default=Path("/tmp/football-optimization-sanitized"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--x11-root", type=Path, default=Path(os.environ.get(
        "FOOTBALL_TEST_X11_ROOT",
        str(Path.home() / ".cache/football-input-x11-20260913-a/root-relocated"))))
    args = parser.parse_args()
    output = (args.output or ROOT / ".project/optimization/benchmarks" /
              ("ai-tactics-" + args.suite + "-" + str(time.time_ns()))).resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = benchmark.source_manifest()
    runner.write_json(output / "sources.json", sources)
    environment = dict(os.environ, PYTHONOPTIMIZE="0",
                       GFOOTBALL_DATA_DIR=str(ROOT / "engine/data"))
    for key in ("LD_PRELOAD", "DISPLAY", "SDL_VIDEODRIVER", "LD_LIBRARY_PATH",
                "GFOOTBALL_FONT", "LSAN_OPTIONS"):
        environment.pop(key, None)
    environment.update(ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                       UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
                       LSAN_OPTIONS="exitcode=23")
    commands, results, binaries = [], {}, {}
    report = dict(passed=False, suite=args.suite, skipped=0)
    previous = signal.signal(signal.SIGTERM, runner.interrupt_command)
    try:
        builds = {"release": args.build.resolve(), "sanitized": args.sanitized_build.resolve()}
        require(builds["release"] != builds["sanitized"], "Builds must be distinct")
        names = (["engine_ai_tactics_contract", "engine_ai_tactics_roles_contract",
                  "engine_ai_touch_contract"] if args.suite == "decisions" else
                 ["engine_ai_tactical_state_contract"])
        # 2026-09-14: the hand-maintained subset omitted the ASan TCP client.
        # targets = names + ([] if args.suite == "decisions" else
        #                    ["football_server", "football_server_tcp", "football_client",
        #                     "engine_native_tactics_replay_contract"])
        targets = names + ([] if args.suite == "decisions" else
                           [*TARGETS, "engine_native_tactics_replay_contract"])

        def run(argv, label, child=environment, timeout=600):
            return runner.run_command(argv, label, output=output, commands=commands,
                                      environment=child, timeout=timeout)

        for label, build in builds.items():
            sanitized = label == "sanitized"
            run(["cmake", "-S", ROOT / "engine", "-B", build,
                 "-DCMAKE_BUILD_TYPE=" + ("Debug" if sanitized else "Release"),
                 "-DBUILD_PYTHON_BINDINGS=OFF",
                 "-DFOOTBALL_ENABLE_SANITIZERS=" + ("ON" if sanitized else "OFF"),
                 "-DFOOTBALL_TEST_X11_ROOT=" + str(args.x11_root.resolve()),
                 "-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=" + str(build / "bin")],
                label + "-configure", timeout=1800)
            run(["cmake", "--build", build, "-j", "1", "--target", *targets],
                label + "-build", timeout=3600)
            recipes = json.loads((build / "compile_commands.json").read_text())
            for row in recipes:
                require("-std=c++23" in row["command"], "Non-C++23 tactical compilation")
                if sanitized:
                    require("-fsanitize=address,undefined" in row["command"] and
                            "-fno-sanitize-recover=all" in row["command"],
                            "Uninstrumented engine translation unit")
            for target in [build / "libfootball_engine.so",
                           *(build / "bin" / name for name in targets)]:
                binaries[str(target)] = benchmark.file_hash(target)
            child = dict(environment, LD_LIBRARY_PATH=str(build))
            for name in names:
                minimum, expected = CONTRACTS[name]
                results[label + "-" + name] = parsed(
                    run([build / "bin" / name], label + "-" + name, child),
                    minimum, expected)
            if args.suite == "integration":
                destination = output / (label + "-network")
                run([sys.executable, ROOT / ".project/checks/native_tactics_probe.py",
                     "--build", build, "--output", destination],
                    label + "-actual-takeover", child, timeout=180)
                network = json.loads((destination / "report.json").read_text())
                require(network["passed"] and network["skipped"] == 0 and
                        len(network["cases"]) == 4, "Incomplete real transport cohort")
                require({(case["kind"], case["seed"], case["depart"])
                         for case in network["cases"]} ==
                        {(kind, 42 + departed, departed)
                         for kind in ("tcp", "udp") for departed in (0, 1)},
                        "Missing team or transport takeover")
                require(all(case["server_exit"] == 0 and case["post_takeover_frames"] >= 151
                            and case["bot_nonzero"] >= 10 and case["human_nonzero"] >= 100
                            and case["hashes"] >= 15 and case["actual_product_server"]
                            for case in network["cases"]), "Incomplete takeover liveness")
                results[label + "-network"] = network

                native_output = output / (label + "-native-client")
                run([sys.executable, ROOT / ".project/checks/native_tactical_client_probe.py",
                     "--server", build / "bin/football_server",
                     "--client", build / "bin/football_client", "--output", native_output],
                    label + "-actual-native-client", child, timeout=180)
                native = json.loads((native_output / "report.json").read_text())
                require(native["passed"] and native["skipped"] == 0 and len(native["cases"]) == 2,
                        "Incomplete actual native client cohort")
                require({case["depart"] for case in native["cases"]} == {0, 1} and
                        all(case["actual_native_client"] and case["client_exit"] == 0 and
                            case["server_exit"] == 0 and case["confirmed"] >= 260 and
                            case["verified_hashes"] >= 25 and case["failed"] == 0
                            for case in native["cases"]), "Native client did not survive takeover")
                results[label + "-native-client"] = native
                boundary_output = output / (label + "-control-boundaries")
                run([sys.executable, ROOT / ".project/checks/native_tactical_control_probe.py",
                     "--build", build, "--output", boundary_output],
                    # 2026-09-14: three bounded startup/response phases; response remains 15s.
                    # label + "-control-boundaries", child, timeout=90)
                    label + "-control-boundaries", child, timeout=180)
                boundary = json.loads((boundary_output / "report.json").read_text())
                require(boundary["passed"] and boundary["skipped"] == 0 and
                        {case["kind"] for case in boundary["cases"]} ==
                        {"fragmented", "invalid_slot", "invalid_frame"} and
                        len(boundary["cases"]) == 3 and
                        all(case["passed"] and case["actual_native_client"]
                            for case in boundary["cases"]), "Incomplete real control parser cases")
                results[label + "-control-boundaries"] = boundary

        # Replay every captured cohort under BOTH builds, including each exact bot decision.
        if args.suite == "integration":
            for label, build in builds.items():
                child = dict(environment, LD_LIBRARY_PATH=str(build))
                for source in builds:
                    for kind in ("tcp", "udp"):
                        for departed in (0, 1):
                            name = f"{kind}-{42 + departed}-{departed}"
                            key = label + "-replay-" + source + "-" + name
                            results[key] = parsed(
                                run([build / "bin/engine_native_tactics_replay_contract",
                                     output / (source + "-network") / name / "authority.bin"],
                                    key, child),
                                700, {"actual_gameenv": True})
        if args.suite == "integration":
            for label, build in builds.items():
                child = dict(environment, LD_LIBRARY_PATH=str(build))
                for source in builds:
                    for departed in (0, 1):
                        directory = output / (source + "-native-client") / ("side-" + str(departed))
                        key = label + "-client-replay-" + source + "-" + str(departed)
                        results[key] = parsed(
                            run([build / "bin/engine_native_tactics_replay_contract",
                                 directory / "authority.bin",
                                 directory / "client" / ("replay_" + str(42 + departed) + ".bin")],
                                key, child),
                            1500, {"actual_gameenv": True})
        require(benchmark.source_manifest() == sources, "Source changed during tactical acceptance")
        for path, digest in binaries.items():
            require(benchmark.file_hash(Path(path)) == digest, "Tactical binary changed during test")
        report.update(passed=True, assertions=sum(row["assertions"] for row in results.values()),
                      results=results, binaries=binaries, actual_product_acceptance=False,
                      hardware_acceptance=False)
    except BaseException as error:
        report.update(error=str(error), results=results, binaries=binaries)
        raise
    finally:
        signal.signal(signal.SIGTERM, previous)
        runner.write_json(output / "report.json", report)
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
