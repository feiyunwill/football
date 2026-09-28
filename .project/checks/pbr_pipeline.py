#!/usr/bin/env python3
"""Fresh native PBR/IBL acceptance against real GameEnv rendering.

The check owns its output directory, serializes every build and capture, and
keeps the failed attempt intact. It intentionally does not grant a milestone:
the quality program combines this check with dependencies and other gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shlex
import signal
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
CHECKS = Path(__file__).resolve().parent
BENCHMARKS = ROOT / ".project/optimization/benchmarks"
sys.path.insert(0, str(CHECKS))
import performance_regression as runner
from input_contract import observation


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(stage: Path, name: str, value: object) -> None:
    (stage / name).write_text(json.dumps(value, indent=2) + "\n")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def terminal_fixture(text: str) -> dict:
    value = json.loads(text.strip().splitlines()[-1])
    require(value["passed"] is True and value["skipped"] == 0,
            "Real GameEnv capture failed or skipped")
    require(value["assertions"] >= 174 and value["actual_gameenv"]
            and value["engine_frames"] >= 161 and value["images"] == 5,
            "Real GameEnv fixture coverage regressed")
    require("Uniform location for shader" not in text,
            "Shader uniform interface error")
    return value


def read_json_lines(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    require(bool(rows), f"Empty probe trace: {path}")
    return rows


def pixel_difference(a: Path, b: Path) -> int:
    first = a.read_bytes()
    second = b.read_bytes()
    require(len(first) == len(second) == 321 * 181 * 3,
            "Unexpected RGB image dimensions")
    return sum(first[i:i+3] != second[i:i+3]
               for i in range(0, len(first), 3))


def frame_paths(directory: Path):
    for frame in [0, 40, 80, 120, 160]:
        for suffix in ["rgb", "state"]:
            yield directory / f"frame-{frame}.{suffix}"


def run_acceptance() -> dict:
    require(platform.system() == "Linux", "Native renderer gate requires Linux")
    require(sys.flags.optimize == 0, "Python assertions must remain enabled")
    stage = BENCHMARKS / f"pbr-pipeline-{time.time_ns()}"
    stage.mkdir(parents=True, exist_ok=False)
    started = time.time()
    process = {
        "pid": os.getpid(),
        "start_ticks": int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "started": started,
    }
    save(stage, "process.json", process)
    parent = observation()
    save(stage, "parent-before.json", parent)
    definition = json.loads((ROOT / ".project/optimization/program.json").read_text())
    check = next(x for x in definition["checks"] if x["id"] == "pbr_pipeline")
    require(check["ready"], "pbr_pipeline check is not enabled")
    sources: dict[str, str] = {}
    for pattern in check["sources"]:
        relative = Path(pattern)
        require(not relative.is_absolute() and ".." not in relative.parts,
                "Source scope escapes repository")
        files = sorted(path for path in ROOT.glob(pattern) if path.is_file())
        require(bool(files), f"Source scope matched no file: {pattern}")
        for path in files:
            sources[str(path.relative_to(ROOT))] = sha(path)
    save(stage, "sources.json", sources)
    pinned: dict[str, str] = {}
    commands: list[dict] = []
    results: dict = {}
    assertions = 0
    exit_code = 1

    def pin(path: Path) -> None:
        path = path.resolve(strict=True)
        key = str(path)
        value = sha(path)
        require(key not in pinned or pinned[key] == value,
                f"Pinned input changed: {key}")
        pinned[key] = value

    for path in [Path(__file__), CHECKS / "performance_regression.py",
                 CHECKS / "input_contract.py", CHECKS / "native_boundary.py",
                 ROOT / ".project/optimization/program.json"]:
        pin(path)
    for name in ["binding_probe.cpp", "resource_probe.cpp",
                 "material_probe.cpp", "rebuild_probe.cpp"]:
        pin(CHECKS / "native_pbr_pipeline" / name)
    for path in [Path("/usr/bin/cmake"), Path("/usr/sbin/c++")]:
        pin(path)
    tool = subprocess.run(["/usr/sbin/c++", "-print-file-name=libasan.so"],
                          capture_output=True, text=True, check=True).stdout.strip()
    require(tool.startswith("/") and Path(tool).is_file(), "libasan is unavailable")
    libasan = str(Path(tool).resolve())
    pin(Path(libasan))
    save(stage, "inputs.json", pinned)

    base_env = dict(os.environ)
    for key in ["LD_PRELOAD", "LD_LIBRARY_PATH", "DISPLAY", "SDL_VIDEODRIVER",
                 "GFOOTBALL_FONT", "GFOOTBALL_USE_PBR",
                 "GFOOTBALL_PBR_BLOOM", "GFOOTBALL_PBR_FXAA",
                 "GFOOTBALL_PBR_EXPOSURE", "GFOOTBALL_PBR_AUTO_EXPOSURE",
                 "FOOTBALL_PBR_BINDING_TRACE",
                "FOOTBALL_PBR_RESOURCE_TRACE", "FOOTBALL_PBR_RELEASE_TRACE",
                "FOOTBALL_MATERIAL_VARIANT", "FOOTBALL_MATERIAL_TRACE",
                "FOOTBALL_IBL_LIGHT_VARIANT", "FOOTBALL_IBL_LIGHT_TRACE",
                "FOOTBALL_IBL_LIGHT_SUMMARY", "FOOTBALL_IBL_DESTRUCTION_TRACE"]:
        base_env.pop(key, None)
    base_env.update(
        PYTHONDONTWRITEBYTECODE="1", PYTHONOPTIMIZE="0",
        ASAN_OPTIONS="halt_on_error=1:detect_leaks=1:quarantine_size_mb=16",
        UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
        LSAN_OPTIONS="exitcode=23",
    )

    def verify() -> None:
        require(observation() == parent, "Parent namespace changed")
        for relative, value in sources.items():
            require(sha(ROOT / relative) == value,
                    f"Canonical source changed: {relative}")
        for path, value in pinned.items():
            require(sha(Path(path)) == value, f"Pinned input changed: {path}")

    def command(argv: list[str], label: str, extra: dict | None = None,
                timeout: int = 300) -> str:
        verify()
        save(stage, "inputs.json", pinned)
        save(stage, "status.json", {"phase": label, "time": time.time()})
        environment = dict(base_env)
        if extra:
            environment.update(extra)
        try:
            return runner.run_command(argv, label, output=stage, commands=commands,
                                      environment=environment, timeout=timeout)
        finally:
            verify()

    def actual_capture(executable: Path, output: Path, label: str,
                       environment: dict) -> dict:
        nonlocal assertions
        text = command([str(executable), str(output)], label, environment)
        value = terminal_fixture(text)
        assertions += value["assertions"]
        maps = (output / "loaded-maps.txt").read_text()
        loaded = {line.split()[-1] for line in maps.splitlines()
                  if "libfootball_engine.so" in line}
        require(loaded == {environment["LD_LIBRARY_PATH"] + "/libfootball_engine.so"},
                f"Unexpected engine core: {loaded}")
        return value

    old_signal = signal.signal(signal.SIGTERM, runner.interrupt_command)
    try:
        include = ROOT / "engine/src"
        fixture_source = ROOT / "engine/tests/engine_frame_capture_contract.cpp"
        require(fixture_source.is_file(), "Native capture contract source missing")
        for mode in ["release", "sanitized"]:
            build = stage / "build" / mode
            output = stage / mode
            output.mkdir()
            sanitized = mode == "sanitized"
            config = [
                "/usr/bin/cmake", "-S", str(ROOT / "engine"), "-B", str(build),
                "-DCMAKE_BUILD_TYPE=" + ("Debug" if sanitized else "Release"),
                "-DBUILD_PYTHON_BINDINGS=OFF", "-DBUILD_RL_TRAINING=OFF",
                "-DFOOTBALL_ENABLE_SANITIZERS=" + ("ON" if sanitized else "OFF"),
                "-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=" + str(build / "bin"),
            ]
            command(config, mode + "-configure", timeout=180)
            cache = (build / "CMakeCache.txt").read_text()
            require("FOOTBALL_RUNTIME_OUTPUT_DIRECTORY:PATH="
                    + str(build / "bin") in cache,
                    "Runtime output escaped private build")
            command(["/usr/bin/cmake", "--build", str(build), "-j", "1",
                     "--target", "engine_frame_capture_contract"],
                    mode + "-build", timeout=1500)
            core = build / "libfootball_engine.so"
            fixture = build / "bin/engine_frame_capture_contract"
            recipe = build / "compile_commands.json"
            for path in [core, fixture, recipe]:
                pin(path)
            rows = [row for row in json.loads(recipe.read_text())
                    if row["file"].endswith("/opengl_renderer3d.cpp")]
            require(len(rows) == 1, "Missing renderer compile command")
            flags = shlex.split(rows[0]["command"])
            if sanitized:
                require(all(flag in flags for flag in [
                    "-g", "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]),
                    "Debug sanitizer flags weakened")
                require(not set(flags).intersection([
                    "-O1", "-O2", "-O3", "-Ofast", "-DNDEBUG"]),
                    "Debug optimization or NDEBUG is forbidden")
            common = {
                "GFOOTBALL_DATA_DIR": str(ROOT / "engine/data"),
                "LIBGL_ALWAYS_SOFTWARE": "1",
                "LD_LIBRARY_PATH": str(build),
            }
            results[mode] = {"captures": {}, "probes": {}}
            for pipeline in ["legacy", "pbr"]:
                env = dict(common)
                if pipeline == "pbr":
                    env["GFOOTBALL_USE_PBR"] = "1"
                target = output / pipeline
                capture = actual_capture(fixture, target,
                                         mode + "-" + pipeline + "-capture", env)
                results[mode]["captures"][pipeline] = capture
            for frame in [0, 40, 80, 120, 160]:
                legacy = output / "legacy" / f"frame-{frame}"
                pbr = output / "pbr" / f"frame-{frame}"
                require((legacy.with_suffix(".state")).read_bytes()
                        == (pbr.with_suffix(".state")).read_bytes(),
                        "Renderer switch changed simulation state")
                require(pixel_difference(legacy.with_suffix(".rgb"),
                                         pbr.with_suffix(".rgb")) > 10000,
                        "PBR switch has no visible contribution")

            libraries: dict[str, Path] = {}
            for name in ["resource", "binding", "material", "rebuild"]:
                source = CHECKS / "native_pbr_pipeline" / f"{name}_probe.cpp"
                library = output / f"lib{name}_probe.so"
                compile = [
                    "/usr/sbin/c++", "-std=c++23", "-fPIC", "-shared",
                    "-I" + str(include), "-I" + str(include / "cmake"),
                    "-I/usr/include/SDL2",
                ]
                if sanitized:
                    compile += ["-g", "-fsanitize=address,undefined",
                                "-fno-sanitize-recover=all",
                                "-fno-omit-frame-pointer"]
                else:
                    compile += ["-O3", "-DNDEBUG"]
                compile += ["-o", str(library), str(source)]
                if name in ["material", "rebuild"]:
                    compile.append(str(core))
                compile += ["-ldl", "-lEGL"]
                command(compile, mode + "-" + name + "-compile", timeout=120)
                pin(library)
                libraries[name] = library

            def probe_env(name: str) -> dict:
                env = dict(common, GFOOTBALL_USE_PBR="1")
                env["LD_PRELOAD"] = (
                    (libasan + ":" if sanitized else "") + str(libraries[name]))
                return env

            resource_out = output / "resource"
            resource_json = output / "resource-readback.json"
            resource_destroy = output / "resource-destruction.jsonl"
            env = probe_env("resource")
            env.update(FOOTBALL_PBR_RESOURCE_TRACE=str(resource_json),
                       FOOTBALL_PBR_RELEASE_TRACE=str(resource_destroy))
            actual_capture(fixture, resource_out, mode + "-resource-capture", env)
            texture = json.loads(resource_json.read_text())["textures"]
            require(texture["irradiance"]["size"] == 32
                    and texture["prefilter_sharp"]["size"] == 128
                    and texture["prefilter_rough"]["size"] == 8
                    and texture["brdf_lut"]["size"] == 128,
                    "IBL target dimensions are incorrect")
            for value in texture.values():
                require(all(math.isfinite(value[key])
                            for key in ["min", "max", "mean"])
                        and value["min"] >= 0
                        and value["max"] > value["min"] + 0.01,
                        "IBL texture is invalid or constant")
            require(texture["prefilter_sharp"]["max"]
                    > texture["prefilter_rough"]["max"] + 0.1,
                    "GGX mip roughness has no response")
            destroyed = read_json_lines(resource_destroy)
            require(all(row["live_before"] == [1, 1, 1]
                        and row["live_after"] == [0, 0, 0]
                        for row in destroyed),
                    "IBL textures were not deleted")
            results[mode]["probes"]["resource"] = {
                "textures": texture, "destructions": destroyed,
            }

            binding_out = output / "binding"
            binding_trace = output / "binding.jsonl"
            env = probe_env("binding")
            env["FOOTBALL_PBR_BINDING_TRACE"] = str(binding_trace)
            actual_capture(fixture, binding_out, mode + "-binding-capture", env)
            snapshots = read_json_lines(binding_trace)
            ibl = [row for row in snapshots
                   if row["phase"] == "fullscreen_entry"
                   and "irradianceMap" in row["uniforms"]]
            require(len(ibl) >= 5, "No actual IBL composition snapshots")
            for row in ibl:
                uniforms = row["uniforms"]
                require(uniforms["irradianceMap"]["values"] == [4]
                        and uniforms["prefilterMap"]["values"] == [5]
                        and uniforms["brdfLUT"]["values"] == [6],
                        "IBL sampler unit mismatch")
                require(row["textures"][4]["cube_width"] == 32
                        and row["textures"][5]["cube_width"] == 128
                        and row["textures"][6]["width"] == 128,
                        "IBL sampler target not bound")
            results[mode]["probes"]["binding_snapshots"] = len(ibl)

            material_results: dict = {}
            for variant in ["baseline", "metal", "rough", "occluded", "split"]:
                target = output / f"material-{variant}"
                trace = output / f"material-{variant}-trace.json"
                env = probe_env("material")
                env.update(FOOTBALL_MATERIAL_VARIANT=variant,
                           FOOTBALL_MATERIAL_TRACE=str(trace))
                actual_capture(fixture, target,
                               mode + "-material-" + variant, env)
                stats = json.loads(trace.read_text())
                n = stats["aux_pixels"]
                require(stats["aux_read"] == 1 and n > 1000,
                        "No material G-buffer data read")
                require(stats["material_indices"] > 1000
                        and stats["uniform_calls"] > 100
                        and stats["same_texture_pairs"] > 100,
                        "Controlled geometry did not reach material batches")
                if variant == "split":
                    require(stats["distinct_uniform_values"] == 2
                            and stats["aux_metal_zero"] > n * 0.5
                            and stats["aux_metal_one"] > 0,
                            "Same-texture material split was lost")
                else:
                    require(stats["distinct_uniform_values"] == 1,
                            "Uniform material variant is not uniform")
                    metal = "aux_metal_one" if variant == "metal" else "aux_metal_zero"
                    rough = "aux_rough_one" if variant == "rough" else "aux_rough_half"
                    ao = "aux_ao_zero" if variant == "occluded" else "aux_ao_one"
                    require(all(stats[key] > n * 0.9 for key in [metal, rough, ao]),
                            "G-buffer M/R/AO does not match controlled input")
                differences = []
                for frame in [0, 40, 80, 120, 160]:
                    baseline = output / "material-baseline" / f"frame-{frame}"
                    current = target / f"frame-{frame}"
                    require(current.with_suffix(".state").read_bytes()
                            == (output / "pbr" / f"frame-{frame}.state").read_bytes(),
                            "Material probe changed simulation state")
                    differences.append(pixel_difference(
                        baseline.with_suffix(".rgb"), current.with_suffix(".rgb")))
                if variant != "baseline":
                    require(min(differences) > (0 if variant == "split" else 1000),
                            "Controlled material did not alter rendered light")
                material_results[variant] = {
                    "trace": stats, "different_pixels": differences,
                }
            results[mode]["probes"]["material"] = material_results

            rebuild_results: dict = {}
            for variant in ["constant", "changed"]:
                target = output / f"rebuild-{variant}"
                trace = output / f"rebuild-{variant}-trace.jsonl"
                summary = output / f"rebuild-{variant}-summary.json"
                destruction = output / f"rebuild-{variant}-destruction.jsonl"
                env = probe_env("rebuild")
                env.update(FOOTBALL_IBL_LIGHT_VARIANT=variant,
                           FOOTBALL_IBL_LIGHT_TRACE=str(trace),
                           FOOTBALL_IBL_LIGHT_SUMMARY=str(summary),
                           FOOTBALL_IBL_DESTRUCTION_TRACE=str(destruction))
                actual_capture(fixture, target,
                               mode + "-rebuild-" + variant, env)
                info = json.loads(summary.read_text())
                rows = read_json_lines(trace)
                releases = read_json_lines(destruction)
                require(info["create_calls"] == info["ibl_draws"]
                        and len(rows) == info["ibl_draws"] >= 5,
                        "IBL creation/composition sequence incomplete")
                require(len(releases) == info["destruction_calls"]
                        == (1 if variant == "constant" else 2),
                        "IBL rebuild destruction count incorrect")
                require(all(row["live_before"] == [1, 1, 1]
                            and row["live_after"] == [0, 0, 0]
                            for row in releases),
                        "Old IBL textures survived rebuild or exit")
                if variant == "constant":
                    require(all(row["irr_mean"] == rows[0]["irr_mean"]
                                for row in rows),
                            "Constant environment changed irradiance")
                else:
                    require(all(row["irr_mean"] == rows[0]["irr_mean"]
                                for row in rows[:3])
                            and all(row["irr_mean"] == rows[3]["irr_mean"]
                                    for row in rows[3:])
                            and max(abs(rows[0]["irr_mean"][i]
                                        - rows[3]["irr_mean"][i])
                                    for i in range(3)) > 0.02
                            and releases[0]["after_create_calls"] == 4,
                            "Changed environment did not rebuild at boundary")
                rebuild_results[variant] = {
                    "summary": info, "trace": rows, "destructions": releases,
                }
            differences = []
            for frame in [0, 40, 80, 120, 160]:
                constant = output / "rebuild-constant" / f"frame-{frame}"
                changed = output / "rebuild-changed" / f"frame-{frame}"
                require(constant.with_suffix(".state").read_bytes()
                        == changed.with_suffix(".state").read_bytes(),
                        "IBL environment input changed simulation state")
                differences.append(pixel_difference(
                    constant.with_suffix(".rgb"), changed.with_suffix(".rgb")))
            require(differences[0] == 0 and min(differences[1:]) > 1000,
                    "IBL environment change has no controlled image response")
            rebuild_results["different_pixels"] = differences
            results[mode]["probes"]["rebuild"] = rebuild_results

            for name in ["resource", "binding", "material-baseline", "material-metal",
                         "material-rough", "material-occluded", "material-split",
                         "rebuild-constant", "rebuild-changed"]:
                target = output / name
                for frame in [0, 40, 80, 120, 160]:
                    require((target / f"frame-{frame}.state").read_bytes()
                            == (output / "pbr" / f"frame-{frame}.state").read_bytes(),
                            "Instrumented render changed simulation state")
            for path in output.rglob("*"):
                if path.is_file():
                    pin(path)
            save(stage, "results.json", results)

        for name in ["legacy", "pbr", "resource", "binding",
                     "material-baseline", "material-metal", "material-rough",
                     "material-occluded", "material-split",
                     "rebuild-constant", "rebuild-changed"]:
            for frame in [0, 40, 80, 120, 160]:
                for suffix in ["rgb", "state"]:
                    first = stage / "release" / name / f"frame-{frame}.{suffix}"
                    second = stage / "sanitized" / name / f"frame-{frame}.{suffix}"
                    require(first.read_bytes() == second.read_bytes(),
                            "Release/Debug image or state diverged")
        verify()
        exit_code = 0
        report = {"passed": True, "assertions": assertions, "skipped": 0,
                  "cases": 22, "actual_gameenv": True,
                  "product_acceptance": False, "stage": str(stage),
                  "results": results}
        save(stage, "report.json", report)
        return {"passed": True, "assertions": assertions, "skipped": 0,
                "cases": 22, "actual_gameenv": True,
                "product_acceptance": False, "stage": str(stage)}
    except BaseException as error:
        traceback.print_exc()
        save(stage, "failure.json",
             {"type": type(error).__name__, "error": str(error)})
        raise
    finally:
        signal.signal(signal.SIGTERM, old_signal)
        save(stage, "commands.json", commands)
        save(stage, "inputs.json", pinned)
        save(stage, "parent-after.json", observation())
        save(stage, "exit.json",
             {"exit_code": exit_code, "started": started, "finished": time.time()})


def main() -> int:
    result = run_acceptance()
    print(json.dumps(result, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
