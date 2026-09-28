#!/usr/bin/env python3
"""Fresh actual-GL image regression against a fixed llvmpipe reference."""
from __future__ import annotations

import hashlib
import json
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
from pbr_pipeline import pixel_difference, terminal_fixture

GOLDEN = CHECKS / "golden/render_images_llvmpipe.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(stage: Path, name: str, value: object) -> None:
    (stage / name).write_text(json.dumps(value, indent=2) + "\n")


def image_metrics(path: Path, width: int, height: int) -> dict:
    data = path.read_bytes()
    require(len(data) == width * height * 3, "RGB frame has wrong dimensions")
    pixels = [data[i:i + 3] for i in range(0, len(data), 3)]
    luma = [(54 * p[0] + 183 * p[1] + 19 * p[2]) // 256
            for p in pixels]
    means = [sum(p[c] for p in pixels) / len(pixels) for c in range(3)]
    sides = [
        [luma[x] for x in range(width)],
        [luma[(height - 1) * width + x] for x in range(width)],
        [luma[y * width] for y in range(height)],
        [luma[y * width + width - 1] for y in range(height)],
    ]

    def edge(x: int, y: int) -> bool:
        index = y * width + x
        return (abs(luma[index] - luma[index + 1]) >= 24 or
                abs(luma[index] - luma[index + width]) >= 24)

    centre = sum(edge(x, y)
                 for y in range(height // 4, 3 * height // 4)
                 for x in range(width // 4, 3 * width // 4))
    border = sum(edge(x, y)
                 for y in range(height - 1)
                 for x in range(width - 1)
                 if x < 12 or x >= width - 12 or
                 y < 12 or y >= height - 12)
    all_edges = sum(edge(x, y)
                    for y in range(height - 1)
                    for x in range(width - 1))
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "mean_rgb": means,
        "mean_luma": sum(luma) / len(luma),
        "nonblack": sum(value > 8 for value in luma),
        "unique_colours": len(set(pixels)),
        "centre_edges": centre,
        "border_edges": border,
        "all_edges": all_edges,
        "edge_coverage": [sum(value > 8 for value in side) / len(side)
                          for side in sides],
    }


def check_images(stage: Path, mode: str, golden: dict) -> dict:
    output = stage / mode
    width, height = golden["size"]
    cases = list(golden["cases"])
    frames = golden["frames"]
    metrics: dict = {}
    for case in cases:
        identity = json.loads((output / case / "identity.json").read_text())
        require(identity == golden["identity"],
                "GL renderer or framebuffer size differs from reference")
        metrics[case] = {}
        for frame in frames:
            image = output / case / f"frame-{frame}.rgb"
            state = output / case / f"frame-{frame}.state"
            value = image_metrics(image, width, height)
            require(value["sha256"] == golden["cases"][case][str(frame)],
                    f"Image baseline changed: {mode}/{case}/{frame}")
            require(sha(state) == golden["states"][str(frame)],
                    f"Simulation baseline changed: {mode}/{case}/{frame}")
            require(value["nonblack"] > 57000
                    and value["unique_colours"] > 1800
                    and 20 < value["mean_luma"] < 150,
                    f"Blank, flat or clipped image: {mode}/{case}/{frame}")
            red, green, blue = value["mean_rgb"]
            require(green > red + 8 and green > blue + 8,
                    f"Pitch colour disappeared: {mode}/{case}/{frame}")
            require(value["centre_edges"] > 250
                    and value["border_edges"] > 400
                    and min(value["edge_coverage"]) > 0.95,
                    f"Image boundary or scene detail disappeared: "
                    f"{mode}/{case}/{frame}")
            metrics[case][str(frame)] = value
    differences = {}
    for case, minimum in [("legacy", 50000), ("fxaa", 10000),
                          ("auto", 10000), ("auto_combined", 10000)]:
        differences[case] = [
            pixel_difference(output / "baseline" / f"frame-{frame}.rgb",
                             output / case / f"frame-{frame}.rgb")
            for frame in frames]
        require(min(differences[case]) > minimum,
                f"Renderer switch did not change pixels: {case}")
    differences["bloom"] = [
        pixel_difference(output / "baseline" / f"frame-{frame}.rgb",
                         output / "bloom" / f"frame-{frame}.rgb")
        for frame in frames]
    require(max(differences["bloom"]) > 500,
            "Bloom did not respond to later bright frames")
    for frame in frames:
        require(metrics["fxaa"][str(frame)]["all_edges"]
                < metrics["baseline"][str(frame)]["all_edges"] - 150,
                "FXAA did not reduce sharp image edges")
        require(metrics["auto"][str(frame)]["mean_luma"]
                > metrics["baseline"][str(frame)]["mean_luma"] + 1,
                "Auto exposure did not increase scene brightness")
    return {"metrics": metrics, "differences": differences}


def run_acceptance() -> dict:
    require(platform.system() == "Linux" and sys.flags.optimize == 0,
            "Native image gate requires Linux and enabled Python assertions")
    stage = ROOT / ".project/optimization/benchmarks" / (
        f"render-images-{time.time_ns()}")
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
    definition = json.loads((ROOT / ".project/optimization/program.json")
                            .read_text())
    check = next(item for item in definition["checks"]
                 if item["id"] == "render_images")
    require(check["ready"], "Formal image check is not enabled")
    golden = json.loads(GOLDEN.read_text())
    require(golden["schema"] == 1 and golden["size"] == [321, 181]
            and golden["frames"] == [0, 40, 80, 120, 160]
            and len(golden["cases"]) == 6,
            "Unexpected image reference layout")
    sources: dict[str, str] = {}
    for pattern in check["sources"]:
        relative = Path(pattern)
        require(not relative.is_absolute() and ".." not in relative.parts,
                "Source scope escapes repository")
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

    for path in [Path(__file__), GOLDEN, CHECKS / "pbr_pipeline.py",
                 CHECKS / "performance_regression.py",
                 CHECKS / "input_contract.py",
                 CHECKS / "native_boundary.py",
                 ROOT / ".project/optimization/program.json",
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
    for key in ["LD_PRELOAD", "LD_LIBRARY_PATH", "DISPLAY",
                "SDL_VIDEODRIVER", "GFOOTBALL_USE_PBR",
                "GFOOTBALL_PBR_BLOOM", "GFOOTBALL_PBR_FXAA",
                "GFOOTBALL_PBR_EXPOSURE", "GFOOTBALL_PBR_AUTO_EXPOSURE"]:
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
                "-DFOOTBALL_ENABLE_SANITIZERS=" + (
                    "ON" if sanitized else "OFF"),
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
                compiled = [row for row in json.loads(recipe.read_text())
                            if row["file"].endswith("/opengl_renderer3d.cpp")]
                require(len(compiled) == 1,
                        "Renderer compile command missing")
                flags = shlex.split(compiled[0]["command"])
                require(all(flag in flags for flag in [
                    "-g", "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]),
                    "Debug sanitizer flags weakened")
            common = {
                "GFOOTBALL_DATA_DIR": str(ROOT / "engine/data"),
                "LIBGL_ALWAYS_SOFTWARE": "1",
                "LD_LIBRARY_PATH": str(build)}
            if sanitized:
                common["LD_PRELOAD"] = libasan
            results[mode] = {"captures": {}}
            for case in golden["cases"]:
                env = dict(common)
                if case != "legacy":
                    env["GFOOTBALL_USE_PBR"] = "1"
                if case in ["bloom", "auto_combined"]:
                    env["GFOOTBALL_PBR_BLOOM"] = "1"
                if case in ["fxaa", "auto_combined"]:
                    env["GFOOTBALL_PBR_FXAA"] = "1"
                if case in ["auto", "auto_combined"]:
                    env["GFOOTBALL_PBR_AUTO_EXPOSURE"] = "1"
                target = output / case
                log = command([str(fixture), str(target)],
                              mode + "-" + case, env)
                value = terminal_fixture(log)
                assertions += value["assertions"]
                loaded = {
                    line.split()[-1]
                    for line in (target / "loaded-maps.txt").read_text()
                    .splitlines() if "libfootball_engine.so" in line}
                require(loaded == {str(core)},
                        "Capture loaded another engine core")
                results[mode]["captures"][case] = value
            results[mode]["images"] = check_images(stage, mode, golden)
            for path in output.rglob("*"):
                if path.is_file():
                    pin(path)
            save(stage, "results.json", results)
        for case in golden["cases"]:
            for frame in golden["frames"]:
                for suffix in ["rgb", "state"]:
                    left = stage / "release" / case / f"frame-{frame}.{suffix}"
                    right = stage / "sanitized" / case / f"frame-{frame}.{suffix}"
                    require(left.read_bytes() == right.read_bytes(),
                            "Release/Debug image or state diverged")
        require(assertions == 2 * len(golden["cases"]) * 174,
                "Real fixture assertion count changed")
        verify()
        exit_code = 0
        report = {
            "passed": True, "assertions": assertions, "skipped": 0,
            "cases": 2 * len(golden["cases"]), "actual_gameenv": True,
            "product_acceptance": False, "stage": str(stage),
            "results": results}
        save(stage, "report.json", report)
        return {key: value for key, value in report.items()
                if key != "results"}
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
        save(stage, "exit.json", {
            "exit_code": exit_code, "started": started,
            "finished": time.time()})


if __name__ == "__main__":
    print(json.dumps(run_acceptance(), separators=(",", ":")), flush=True)
