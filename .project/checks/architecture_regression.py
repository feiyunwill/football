#!/usr/bin/env python3
"""Instrument the complete native engine and exercise actual architecture boundaries."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

# 2026-09-14: complete engine instrumentation includes fresh product entry points.
# from native_boundary import ROOT, require, run
from native_boundary import ROOT, TARGETS, require, run
import ai_reachability_contract
# 2026-09-15: resource preparation and cancellation are architecture boundaries.
import loading_regression


def probe(binary, arguments, environment, minimum):
    print("Running instrumented probe: " + " ".join(map(str, [binary, *arguments])), flush=True)
    output = subprocess.run([str(binary), *map(str, arguments)], cwd=ROOT, env=environment,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
    print(output.stdout, flush=True)
    require(output.returncode == 0, f"Sanitized probe exited {output.returncode}")
    reports = [json.loads(line) for line in output.stdout.splitlines() if line.startswith('{"passed"')]
    require(len(reports) == 1, "Missing/ambiguous architecture report")
    result = reports[0]
    require(result.get("passed") is True and result.get("skipped") == 0 and
            result.get("assertions", 0) >= minimum, "Incomplete architecture probe")
    require("runtime error:" not in output.stdout and "ERROR: AddressSanitizer" not in output.stdout
            and "ERROR: LeakSanitizer" not in output.stdout, "Sanitizer diagnostic in successful output")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-sanitized"))
    args = parser.parse_args()
    build = args.build.resolve()
    run(["cmake", "-S", "engine", "-B", build, "-DCMAKE_BUILD_TYPE=Debug",
         "-DBUILD_PYTHON_BINDINGS=OFF", "-DFOOTBALL_ENABLE_SANITIZERS=ON",
         f"-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / 'bin'}"])
    commands = json.loads((build / "compile_commands.json").read_text())
    require(len(commands) >= 100, "Not a full-engine compilation database")
    for command in commands:
        require("-fsanitize=address,undefined" in command["command"] and
                "-fno-sanitize-recover=all" in command["command"] and
                "-fno-omit-frame-pointer" in command["command"],
                f"Uninstrumented translation unit: {command['file']}")
    # 2026-09-09: include native animation metadata boundaries in full instrumentation.
    # run(["cmake", "--build", build, "-j", "1", "--target", "engine_architecture_contract",
    #      "engine_lifetime_contract", "engine_simulation_contract", "standalone_game"])
    run(["cmake", "--build", build, "-j", "1", "--target", "engine_architecture_contract",
         "engine_lifetime_contract", "engine_simulation_contract", "standalone_game",
         # 2026-09-13: previous target list ended at engine_animation_query_contract.
         # 2026-09-14: keep the previous animation/reachability targets and add touch decisions.
         # "engine_animation_query_contract", "engine_ai_reachability_contract"])
         # 2026-09-14: preserve the previous target list and add owned tactical observation.
         # "engine_animation_query_contract", "engine_ai_reachability_contract", "engine_ai_touch_contract"])
         "engine_animation_query_contract", "engine_ai_reachability_contract", "engine_ai_touch_contract",
         "engine_ai_tactical_state_contract", "engine_ai_tactics_contract",
         # 2026-09-14: include all canonical native products, not only test harnesses.
         # "engine_ai_tactics_roles_contract"])
         # 2026-09-15: keep the original products and add permanent loading contracts.
         # "engine_ai_tactics_roles_contract", *TARGETS])
         "engine_ai_tactics_roles_contract", *TARGETS, *loading_regression.TARGETS])
    dynamic = run(["readelf", "-d", build / "libfootball_engine.so"], capture=True)
    # GCC links separate runtimes; the exported ASan/UBSan calls prove instrumentation
    # on toolchains that link the runtime into the executable instead.
    symbols = run(["nm", "-D", build / "libfootball_engine.so"], capture=True)
    require("__asan_" in symbols and "__ubsan_" in symbols, "Engine lacks sanitizer instrumentation")
    environment = dict(os.environ)
    for key in ("DISPLAY", "GFOOTBALL_DATA_DIR", "GFOOTBALL_FONT", "LD_PRELOAD", "SDL_VIDEODRIVER"):
        environment.pop(key, None)
    environment.update(ASAN_OPTIONS="halt_on_error=1:detect_leaks=1:quarantine_size_mb=16",
                       UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
                       LSAN_OPTIONS="exitcode=23", LIBGL_ALWAYS_SOFTWARE="1")
    results = {}
    # 2026-09-15: full-engine sanitizers cover all 26 cancellation boundaries.
    results["loading"] = loading_regression.probe(build, environment)
    # 2026-09-14: the complete instrumented engine must preserve tactical observation and HID purity.
    from ai_tactics_contract import CONTRACTS
    for name in ("engine_ai_tactical_state_contract", "engine_ai_tactics_contract",
                 "engine_ai_tactics_roles_contract"):
        minimum, expected = CONTRACTS[name]
        result = probe(build / ("bin/" + name), [], environment, minimum)
        require(all(result.get(key) == value for key, value in expected.items()),
                "Incomplete tactical architecture coverage")
        results[name] = result
    # 2026-09-14: full-engine sanitizers must exercise the corrected touch branch.
    results["ai_touch"] = probe(build / "bin/engine_ai_touch_contract", [], environment, 586)
    require(all(results["ai_touch"].get(key) == value for key, value in
                {"assertions": 586, "seeds": 3, "ball_control_assets": 270,
                 "quiet_idle": 24, "actual_gameenv": True}.items()),
            "Incomplete real touch-decision cohort")
    results["ai_reachability"] = ai_reachability_contract.probe(build, environment)
    results["animation_metadata"] = probe(build / "bin/engine_animation_query_contract",
                                          [], environment, 30000)
    architecture = build / "bin/engine_architecture_contract"
    simulation = build / "bin/engine_simulation_contract"
    for seed in (42, 43):
        # 2026-09-09: include whole-frame rejection alongside lifecycle/input tests.
        # results[f"lifecycle_{seed}"] = probe(architecture, ["headless", seed], environment, 195)
        # 2026-09-09: include local/authoritative four-slot trajectory equivalence.
        # results[f"lifecycle_{seed}"] = probe(architecture, ["headless", seed], environment, 215)
        results[f"lifecycle_{seed}"] = probe(architecture, ["headless", seed], environment, 296)
        results[f"egl_lifecycle_{seed}"] = probe(architecture, ["render", seed], environment, 51)
        for name, extra in (("normal", []), ("reverse", ["--reverse"]), ("render", ["--render"])):
            results[f"snapshot_{seed}_{name}"] = probe(simulation, [seed, *extra], environment,
                                                      92 if name == "render" else 800)
    results["repeated_and_concurrent_instances"] = probe(build / "bin/engine_lifetime_contract", [], environment, 167)
    results["two_egl_contexts"] = probe(build / "bin/engine_lifetime_contract", ["--render"], environment, 9)
    # SDL's offscreen video driver creates an actual SDL GL window/context without
    # opening a window on the user's desktop; this is distinct from the direct EGL path.
    results["sdl_events"] = probe(architecture, ["sdl"],
                                  dict(environment, DISPLAY=":football-test", SDL_VIDEODRIVER="offscreen"), 17)
    results["sdl_context_failure"] = probe(architecture, ["sdl-failure"],
            dict(environment, DISPLAY=":football-test", SDL_VIDEODRIVER="dummy"), 5)
    with tempfile.TemporaryDirectory(prefix="football-invalid-font-") as directory:
        invalid = Path(directory) / "invalid.ttf"
        invalid.write_bytes(b"not a font")
        for label, font in (("invalid", invalid), ("missing", invalid.with_name("missing.ttf"))):
            results[f"{label}_font_failure"] = probe(architecture, ["font-failure"],
                                                    dict(environment, GFOOTBALL_FONT=str(font)), 5)
    print(json.dumps({"passed": True, "assertions": sum(item["assertions"] for item in results.values()),
                      "skipped": 0, "results": results, "instrumented_translation_units": len(commands),
                      "instrumentation": "complete engine ASan/UBSan, leak detection enabled, no suppressions",
                      "asan_runtime_in_engine": "libasan" in dynamic,
                      "sdl_driver": "offscreen (real SDL GL window and event queue)"}))


if __name__ == "__main__":
    main()
