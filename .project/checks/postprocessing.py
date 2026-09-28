#!/usr/bin/env python3
"""Fresh GameEnv acceptance for PBR postprocessing and GPU auto exposure."""
from __future__ import annotations

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
sys.path.insert(0, str(CHECKS))
import performance_regression as runner
from input_contract import observation
from pbr_pipeline import terminal_fixture, pixel_difference

CASES = [
    "legacy", "legacy_flags", "baseline", "bloom", "fxaa", "combined",
    "exposure2", "exposure_half", "auto", "auto_override",
    "auto_combined", "traced_combined", "traced_auto",
]
FRAMES = [0, 40, 80, 120, 160]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(stage: Path, name: str, value: object) -> None:
    (stage / name).write_text(json.dumps(value, indent=2) + "\n")


def rows(path: Path) -> list[dict]:
    result = [json.loads(line) for line in path.read_text().splitlines()]
    require(bool(result), f"Empty GL trace: {path}")
    return result


def rgb(stage: Path, mode: str, case: str, frame: int) -> Path:
    return stage / mode / case / f"frame-{frame}.rgb"


def state(stage: Path, mode: str, case: str, frame: int) -> Path:
    return stage / mode / case / f"frame-{frame}.state"


def check_effects(stage: Path, mode: str) -> dict:
    metrics: dict = {}
    for case in CASES:
        for frame in FRAMES:
            require(state(stage, mode, case, frame).read_bytes()
                    == state(stage, mode, "baseline", frame).read_bytes(),
                    "Postprocess option changed simulation state")
    for frame in FRAMES:
        require(rgb(stage, mode, "legacy_flags", frame).read_bytes()
                == rgb(stage, mode, "legacy", frame).read_bytes(),
                "PBR postprocess options changed Legacy output")
        require(rgb(stage, mode, "traced_combined", frame).read_bytes()
                == rgb(stage, mode, "combined", frame).read_bytes(),
                "GL probes changed combined output")
        require(rgb(stage, mode, "traced_auto", frame).read_bytes()
                == rgb(stage, mode, "auto", frame).read_bytes(),
                "GL probes changed auto exposure output")
        require(rgb(stage, mode, "auto_override", frame).read_bytes()
                == rgb(stage, mode, "auto", frame).read_bytes(),
                "Manual exposure overrode enabled auto exposure")
    for case in ["bloom", "fxaa", "combined", "exposure2",
                 "exposure_half", "auto", "auto_combined"]:
        metrics[case] = [pixel_difference(
            rgb(stage, mode, "baseline", frame),
            rgb(stage, mode, case, frame)) for frame in FRAMES]
    require(max(metrics["bloom"]) > 500
            and min(metrics["fxaa"]) > 10000
            and min(metrics["auto"]) > 10000,
            "Enabled effect has no meaningful image response")
    require(all(pixel_difference(
        rgb(stage, mode, "fxaa", frame),
        rgb(stage, mode, "combined", frame)) > 0
        for frame in FRAMES[2:]), "Bloom was lost when FXAA was enabled")
    for frame in FRAMES:
        low = sum(rgb(stage, mode, "exposure_half", frame).read_bytes())
        mid = sum(rgb(stage, mode, "baseline", frame).read_bytes())
        high = sum(rgb(stage, mode, "exposure2", frame).read_bytes())
        require(low < mid < high, "Manual exposure is not monotonic")
    return metrics


def check_combined_gl(stage: Path, mode: str) -> dict:
    output = stage / mode
    binding = rows(output / "combined-binding.jsonl")
    lifetime = rows(output / "combined-lifetime.jsonl")
    require(len(lifetime) == 1, "Expected one View release")
    owner = lifetime[0]
    textures = owner["textures"]
    fbos = owner["framebuffers"]
    require(len(textures) == len(fbos) == 5
            and all(value > 0 for value in textures[:3] + fbos[:3])
            and textures[3:] == fbos[3:] == [0, 0],
            "Combined targets are incomplete")
    require(owner["before_textures"] == owner["before_framebuffers"]
            == [1, 1, 1, 0, 0]
            and owner["after_textures"] == owner["after_framebuffers"]
            == [0, 0, 0, 0, 0],
            "Combined targets survived View deletion")
    passes = []
    for row in binding:
        if row["phase"] != "fullscreen_entry":
            continue
        uniforms = row["uniforms"]
        if "bloomThreshold" in uniforms:
            kind = "extract"
        elif "direction" in uniforms:
            kind = ("horizontal" if uniforms["direction"]["values"] == [1, 0]
                    else "vertical")
        elif "bloomStrength" in uniforms:
            kind = "tone"
        elif "fxaaReduceMin" in uniforms:
            kind = "fxaa"
        else:
            continue
        passes.append((kind, row))
    require(len(passes) == 75, "Expected 15 real postprocess pass cycles")
    for index in range(0, len(passes), 5):
        cycle = passes[index:index + 5]
        require([kind for kind, _ in cycle]
                == ["extract", "horizontal", "vertical", "tone", "fxaa"],
                "Postprocess pass order changed")
        extract, horizontal, vertical, tone, fxaa = [row for _, row in cycle]
        require(extract["fbo"] == fbos[0]
                and horizontal["fbo"] == fbos[1]
                and vertical["fbo"] == fbos[0]
                and tone["fbo"] == fbos[2] and fxaa["fbo"] == 0,
                "Postprocess destination FBO mismatch")
        require(extract["viewport"] == horizontal["viewport"]
                == vertical["viewport"] == [0, 0, 160, 90]
                and tone["viewport"] == fxaa["viewport"]
                == [0, 0, 321, 181],
                "Postprocess dimensions mismatch")
        require(extract["textures"][0]["width"] == 321
                and horizontal["textures"][0]["texture2d"] == textures[0]
                and vertical["textures"][0]["texture2d"] == textures[1]
                and tone["textures"][0]["texture2d"]
                == extract["textures"][0]["texture2d"]
                and tone["textures"][1]["texture2d"] == textures[0]
                and tone["textures"][2]["texture2d"] > 0
                and fxaa["textures"][0]["texture2d"] == textures[2],
                "Postprocess sampler has no real source texture")
        require(tone["uniforms"]["bloomStrength"]["values"][0] > 0.29,
                "Bloom compositing is disabled")
    return {"cycles": len(passes) // 5, "textures": textures, "fbos": fbos}


def check_auto_gl(stage: Path, mode: str) -> dict:
    output = stage / mode
    binding = rows(output / "auto-binding.jsonl")
    exposure = rows(output / "auto-exposure.jsonl")
    lifetime = rows(output / "auto-lifetime.jsonl")
    require(len(lifetime) == 1 and len(exposure) == 15,
            "Auto exposure trace is incomplete")
    owner = lifetime[0]
    textures = owner["textures"]
    fbos = owner["framebuffers"]
    require(textures[:3] == fbos[:3] == [0, 0, 0]
            and len(set(textures[3:])) == len(set(fbos[3:])) == 2
            and all(value > 0 for value in textures[3:] + fbos[3:]),
            "Auto exposure ping-pong targets are missing")
    require(owner["before_textures"] == owner["before_framebuffers"]
            == [0, 0, 0, 1, 1]
            and owner["after_textures"] == owner["after_framebuffers"]
            == [0, 0, 0, 0, 0],
            "Auto exposure targets survived View deletion")
    auto_pass = [row for row in binding if row["phase"] == "fullscreen_entry"
                 and "map_previousExposure" in row["uniforms"]]
    tone_pass = [row for row in binding if row["phase"] == "fullscreen_entry"
                 and "useAutoExposure" in row["uniforms"]]
    require(len(auto_pass) == 5 and len(tone_pass) == 15,
            "Repeated presentation advanced auto exposure")
    for step in range(5):
        current = exposure[step * 3:step * 3 + 3]
        first = current[0]
        previous = 1.0 if step == 0 else exposure[step * 3 - 1]["exposure"]
        require(all(row["texture"] == first["texture"]
                    and row["exposure"] == first["exposure"]
                    and row["target"] == first["target"] for row in current),
                "Same simulation state changed exposure")
        require(first["texture"] == textures[4 - step % 2]
                and auto_pass[step]["fbo"] == fbos[4 - step % 2]
                and auto_pass[step]["viewport"] == [0, 0, 1, 1],
                "Exposure ping-pong order is wrong")
        require(auto_pass[step]["textures"][0]["width"] == 321
                and auto_pass[step]["textures"][1]["texture2d"]
                == textures[3 + step % 2],
                "Metering did not read HDR and previous exposure")
        require(all(tone_pass[step * 3 + repeat]["textures"][3]["texture2d"]
                    == first["texture"]
                    and tone_pass[step * 3 + repeat]["uniforms"]
                    ["useAutoExposure"]["values"] == [1]
                    for repeat in range(3)),
                "Tone mapping did not sample current exposure")
        require(math.isfinite(first["exposure"])
                and math.isfinite(first["target"])
                and 0.1 <= first["exposure"] <= 8
                and 0.1 <= first["target"] <= 8
                and abs(first["target"] * first["average_luminance"]
                        - 0.18) < 0.005
                and abs(first["exposure"]
                        - (previous + 0.125 * (first["target"] - previous)))
                < 0.002, "GPU exposure math is incorrect")
    require(max(row["target"] for row in exposure)
            - min(row["target"] for row in exposure) > 0.02,
            "Scene luminance did not affect exposure target")
    return {"updates": len(auto_pass), "tone_draws": len(tone_pass),
            "range": [min(row["exposure"] for row in exposure),
                      max(row["exposure"] for row in exposure)]}


def run_acceptance() -> dict:
    require(platform.system() == "Linux" and sys.flags.optimize == 0,
            "Native check requires Linux and enabled Python assertions")
    stage = ROOT / ".project/optimization/benchmarks" / (
        f"postprocessing-{time.time_ns()}")
    stage.mkdir(parents=True, exist_ok=False)
    started = time.time()
    save(stage, "process.json", {
        "pid": os.getpid(),
        "start_ticks": int(Path("/proc/self/stat").read_text()
                           .rsplit(")", 1)[1].split()[19]),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "started": started})
    parent = observation()
    save(stage, "parent-before.json", parent)
    definition = json.loads((ROOT / ".project/optimization/program.json").read_text())
    check = next(item for item in definition["checks"]
                 if item["id"] == "postprocessing")
    require(check["ready"], "Formal postprocessing check is not enabled")
    sources: dict[str, str] = {}
    for pattern in check["sources"]:
        paths = sorted(path for path in ROOT.glob(pattern) if path.is_file())
        require(bool(paths), f"Empty source scope: {pattern}")
        for path in paths:
            sources[str(path.relative_to(ROOT))] = sha(path)
    save(stage, "sources.json", sources)
    pinned: dict[str, str] = {}
    commands: list[dict] = []
    results: dict = {}
    assertions = 0
    exit_code = 1

    def pin(path: Path) -> None:
        path = path.resolve(strict=True)
        digest = sha(path)
        old = pinned.get(str(path))
        require(old is None or old == digest, f"Pinned input changed: {path}")
        pinned[str(path)] = digest

    for path in [Path(__file__), CHECKS / "performance_regression.py",
                 CHECKS / "pbr_pipeline.py", CHECKS / "input_contract.py",
                 CHECKS / "native_boundary.py",
                 ROOT / ".project/optimization/program.json",
                 ROOT / ".project/checks/native_pbr_pipeline/binding_probe.cpp",
                 CHECKS / "native_postprocessing/lifetime_probe.cpp",
                 CHECKS / "native_postprocessing/exposure_probe.cpp",
                 Path("/usr/bin/cmake"), Path("/usr/sbin/c++")]:
        pin(path)
    libasan = subprocess.run(
        ["/usr/sbin/c++", "-print-file-name=libasan.so"],
        capture_output=True, text=True, check=True).stdout.strip()
    require(libasan.startswith("/") and Path(libasan).is_file(),
            "libasan unavailable")
    libasan = str(Path(libasan).resolve())
    pin(Path(libasan))
    save(stage, "inputs.json", pinned)

    base_env = dict(os.environ)
    for key in ["LD_PRELOAD", "LD_LIBRARY_PATH", "DISPLAY", "SDL_VIDEODRIVER",
                "GFOOTBALL_USE_PBR", "GFOOTBALL_PBR_BLOOM",
                "GFOOTBALL_PBR_FXAA", "GFOOTBALL_PBR_EXPOSURE",
                "GFOOTBALL_PBR_AUTO_EXPOSURE", "FOOTBALL_PBR_BINDING_TRACE",
                "FOOTBALL_POSTPROCESS_LIFETIME_TRACE",
                "FOOTBALL_POSTPROCESS_EXPOSURE_TRACE"]:
        base_env.pop(key, None)
    base_env.update(
        PYTHONDONTWRITEBYTECODE="1", PYTHONOPTIMIZE="0",
        ASAN_OPTIONS="halt_on_error=1:detect_leaks=1:quarantine_size_mb=16",
        UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
        LSAN_OPTIONS="exitcode=23")

    def verify() -> None:
        require(observation() == parent, "Parent namespace changed")
        for relative, digest in sources.items():
            require(sha(ROOT / relative) == digest,
                    f"Source changed: {relative}")
        for name, digest in pinned.items():
            require(sha(Path(name)) == digest, f"Input changed: {name}")

    def command(argv: list[str], label: str, env: dict | None = None,
                timeout: int = 300) -> str:
        verify()
        save(stage, "status.json", {"phase": label, "time": time.time()})
        environment = dict(base_env)
        if env:
            environment.update(env)
        try:
            return runner.run_command(
                argv, label, output=stage, commands=commands,
                environment=environment, timeout=timeout)
        finally:
            verify()

    old_signal = signal.signal(signal.SIGTERM, runner.interrupt_command)
    try:
        for mode in ["release", "sanitized"]:
            build = stage / "build" / mode
            output = stage / mode
            output.mkdir()
            sanitized = mode == "sanitized"
            command([
                "/usr/bin/cmake", "-S", str(ROOT / "engine"), "-B", str(build),
                "-DCMAKE_BUILD_TYPE=" + ("Debug" if sanitized else "Release"),
                "-DBUILD_PYTHON_BINDINGS=OFF", "-DBUILD_RL_TRAINING=OFF",
                "-DFOOTBALL_ENABLE_SANITIZERS=" + ("ON" if sanitized else "OFF"),
                "-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=" + str(build / "bin")],
                mode + "-configure", timeout=180)
            command(["/usr/bin/cmake", "--build", str(build), "-j", "1",
                     "--target", "engine_frame_capture_contract"],
                    mode + "-build", timeout=1500)
            core = build / "libfootball_engine.so"
            fixture = build / "bin/engine_frame_capture_contract"
            recipe = build / "compile_commands.json"
            for path in [core, fixture, recipe]:
                pin(path)
            if sanitized:
                rows_compiled = [row for row in json.loads(recipe.read_text())
                                 if row["file"].endswith("/opengl_renderer3d.cpp")]
                require(len(rows_compiled) == 1, "Renderer compile command missing")
                flags = shlex.split(rows_compiled[0]["command"])
                require(all(flag in flags for flag in [
                    "-g", "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]),
                    "Debug sanitizer flags weakened")
            libraries = {}
            for name, source in [
                    ("binding", CHECKS / "native_pbr_pipeline/binding_probe.cpp"),
                    ("lifetime", CHECKS / "native_postprocessing/lifetime_probe.cpp"),
                    ("exposure", CHECKS / "native_postprocessing/exposure_probe.cpp")]:
                library = output / f"lib{name}.so"
                compile = [
                    "/usr/sbin/c++", "-std=c++23", "-fPIC", "-shared",
                    "-I" + str(ROOT / "engine/src"),
                    "-I" + str(ROOT / "engine/src/cmake"),
                    "-I/usr/include/SDL2"]
                if sanitized:
                    compile += ["-g", "-fsanitize=address,undefined",
                                "-fno-sanitize-recover=all",
                                "-fno-omit-frame-pointer"]
                else:
                    compile += ["-O3", "-DNDEBUG"]
                compile += ["-o", str(library), str(source), "-ldl", "-lEGL"]
                command(compile, mode + "-" + name + "-compile", timeout=120)
                pin(library)
                libraries[name] = library
            common = {
                "GFOOTBALL_DATA_DIR": str(ROOT / "engine/data"),
                "LIBGL_ALWAYS_SOFTWARE": "1",
                "LD_LIBRARY_PATH": str(build)}
            results[mode] = {"captures": {}}
            for case in CASES:
                env = dict(common)
                if case not in ["legacy", "legacy_flags"]:
                    env["GFOOTBALL_USE_PBR"] = "1"
                if case in ["legacy_flags", "bloom", "combined",
                            "auto_combined", "traced_combined"]:
                    env["GFOOTBALL_PBR_BLOOM"] = "1"
                if case in ["legacy_flags", "fxaa", "combined",
                            "auto_combined", "traced_combined"]:
                    env["GFOOTBALL_PBR_FXAA"] = "1"
                if case in ["legacy_flags", "exposure2", "auto_override"]:
                    env["GFOOTBALL_PBR_EXPOSURE"] = "2.0"
                if case == "exposure_half":
                    env["GFOOTBALL_PBR_EXPOSURE"] = "0.5"
                if case in ["auto", "auto_override", "auto_combined",
                            "traced_auto"]:
                    env["GFOOTBALL_PBR_AUTO_EXPOSURE"] = "1"
                if case in ["traced_combined", "traced_auto"]:
                    traced_auto = case == "traced_auto"
                    ordered = ([libasan] if sanitized else []) + [
                        str(libraries["binding"])]
                    if traced_auto:
                        ordered.append(str(libraries["exposure"]))
                    ordered.append(str(libraries["lifetime"]))
                    env["LD_PRELOAD"] = ":".join(ordered)
                    prefix = "auto" if traced_auto else "combined"
                    env["FOOTBALL_PBR_BINDING_TRACE"] = str(
                        output / (prefix + "-binding.jsonl"))
                    env["FOOTBALL_POSTPROCESS_LIFETIME_TRACE"] = str(
                        output / (prefix + "-lifetime.jsonl"))
                    if traced_auto:
                        env["FOOTBALL_POSTPROCESS_EXPOSURE_TRACE"] = str(
                            output / "auto-exposure.jsonl")
                elif sanitized:
                    env["LD_PRELOAD"] = libasan
                target = output / case
                log = command([str(fixture), str(target)],
                              mode + "-" + case, env)
                value = terminal_fixture(log)
                assertions += value["assertions"]
                mapped = (target / "loaded-maps.txt").read_text()
                loaded = {line.split()[-1] for line in mapped.splitlines()
                          if "libfootball_engine.so" in line}
                require(loaded == {str(core)}, "Capture loaded another engine core")
                results[mode]["captures"][case] = value
            results[mode]["differences"] = check_effects(stage, mode)
            results[mode]["combined_gl"] = check_combined_gl(stage, mode)
            results[mode]["auto_gl"] = check_auto_gl(stage, mode)
            for path in output.rglob("*"):
                if path.is_file():
                    pin(path)
            save(stage, "results.json", results)
        for case in CASES:
            for frame in FRAMES:
                for suffix in ["rgb", "state"]:
                    left = stage / "release" / case / f"frame-{frame}.{suffix}"
                    right = stage / "sanitized" / case / f"frame-{frame}.{suffix}"
                    require(left.read_bytes() == right.read_bytes(),
                            "Release/Debug postprocess output diverged")
        require(assertions == len(CASES) * 2 * 174,
                "Real fixture assertion count changed")
        verify()
        exit_code = 0
        report = {
            "passed": True, "assertions": assertions, "skipped": 0,
            "cases": len(CASES) * 2, "actual_gameenv": True,
            "product_acceptance": False, "stage": str(stage),
            "results": results}
        save(stage, "report.json", report)
        return {key: value for key, value in report.items() if key != "results"}
    except BaseException as error:
        traceback.print_exc()
        save(stage, "failure.json",
             {"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        signal.signal(signal.SIGTERM, old_signal)
        save(stage, "commands.json", commands)
        save(stage, "inputs.json", pinned)
        save(stage, "parent-after.json", observation())
        save(stage, "exit.json",
             {"exit_code": exit_code, "started": started, "finished": time.time()})


if __name__ == "__main__":
    print(json.dumps(run_acceptance(), separators=(",", ":")), flush=True)
