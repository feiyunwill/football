"""Exercise actual GameEnv pixels across rollback and an in-flight retarget."""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png(pixels, path):
    width, height = 1280, 720
    require(len(pixels) == width * height * 3, "Unexpected actual framebuffer size")

    def chunk(kind, value):
        return (struct.pack(">I", len(value)) + kind + value +
                struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff))

    rows = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3]
                    for y in range(height))
    payload = (b"\x89PNG\r\n\x1a\n" +
               chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
               chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))
    path.write_bytes(payload)
    return {"sha256": sha(path), "rgb_sha256": hashlib.sha256(pixels).hexdigest(),
            "bytes": len(payload), "width": width, "height": height}


def worker(output):
    from gfootball.engine_pool import ENGINE_POOL
    from gfootball.frame_sync.match_archive import engine_digest
    from gfootball.frame_sync.match_identity import engine_identity, native_match_display, native_match_engine
    from gfootball.frame_sync.protocol import SlotInput, pack_slot_input
    from gfootball.frame_sync.server_runtime import ServerSettings
    import gfootball_engine
    import gfootball_engine._gameplayfootball as binding

    output.mkdir(parents=True, exist_ok=False)
    images = output / "images"
    images.mkdir()
    frames = {}
    checks = 0

    def capture(name, display):
        nonlocal checks
        rgb = display.get_frame()
        frames[name] = png(rgb, images / (name + ".png"))
        checks += 1
        return rgb

    settings = ServerSettings()
    with native_match_engine(settings) as logic:
        with native_match_display(settings, engine_identity(logic)) as display:
            origin = logic.get_state("")
            display.set_state(origin)
            display.render()
            require(engine_digest(display) == engine_digest(logic), "Initial display changed physics")
            checks += 1

            # Speculative path A is visible only partway through its transition.
            display.save_render_state()
            for _ in range(8):
                logic.step_with_input(pack_slot_input(SlotInput(.8, .3, 4)))
            speculative = engine_digest(logic)
            display.set_state(logic.get_state(""))
            display.render_interpolated(.4)
            visible = capture("visible_before_rollback", display)
            require(engine_digest(display) == speculative, "Visible blend mutated speculative physics")
            checks += 1

            # Restore the same source frame, then take a different input path.
            logic.set_state(origin)
            for _ in range(8):
                logic.step_with_input(pack_slot_input(SlotInput(-.8, -.3, 0)))
            corrected = engine_digest(logic)
            require(corrected != speculative, "Rollback did not create a different target")
            display.save_render_state(from_display=True)
            display.set_state(logic.get_state(""))
            for alpha, name in ((0., "correction_start"), (.5, "correction_middle")):
                display.render_interpolated(alpha)
                capture(name, display)
                require(engine_digest(display) == corrected, "Correction blend mutated physics")
                checks += 1
            require(display.get_frame() != visible, "Correction has no visible intermediate")
            require(frames["correction_start"]["rgb_sha256"] ==
                    frames["visible_before_rollback"]["rgb_sha256"],
                    "Rollback jumped at its first displayed frame")
            checks += 2
            middle = display.get_frame()

            # A second target arrives before the first correction finishes.
            for _ in range(3):
                logic.step_with_input(pack_slot_input(SlotInput(-.8, .2, 0)))
            retargeted = engine_digest(logic)
            display.save_render_state(from_display=True)
            display.set_state(logic.get_state(""))
            display.render_interpolated(0.)
            capture("retarget_start", display)
            require(display.get_frame() == middle, "New target jumped from the in-flight visible pose")
            require(engine_digest(display) == retargeted, "Retarget changed logic state")
            checks += 2
            display.render_interpolated(1.)
            final = capture("retarget_end", display)
            require(final != middle, "Retarget did not reach a new visible endpoint")
            require(engine_digest(display) == retargeted, "Final render changed physics")
            checks += 2

            # The same rendered endpoint remains stable through a long pause.
            display.save_render_state(from_display=True)
            for _ in range(12):
                display.render_interpolated(0.)
                require(display.get_frame() == final and engine_digest(display) == retargeted,
                        "Paused render changed a visible or logical state")
                checks += 1
            capture("paused_endpoint", display)
    require(ENGINE_POOL.stats()["live"] == 0, "Native engine pool leaked after correction")
    checks += 1
    report = {"passed": True, "skipped": 0, "assertions": checks,
              "actual_gameenv": True, "actual_pixels": True,
              "rollback_from_visible": True, "inflight_retarget": True,
              "paused_endpoint_stable": True, "images": frames,
              "native_loader": str(Path(gfootball_engine.__file__).resolve()),
              "native_binding": str(Path(binding.__file__).resolve()),
              "physics": {"speculative": speculative, "corrected": corrected,
                          "retargeted": retargeted}}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-presentation-native-20261001"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    output = (args.output or ROOT / ".project/optimization/benchmarks" /
              f"presentation-smoothing-{time.time_ns()}").resolve()
    if args.worker:
        worker(output)
        return
    require(sys.flags.optimize == 0 and sys.platform == "linux", "Linux assertions are required")
    require(output.is_relative_to(ROOT / ".project/optimization/benchmarks") and not output.exists(),
            "Use a new workspace evidence directory")
    output.mkdir(parents=True)
    sys.path.insert(0, str(ROOT / ".project"))
    from quality import Program
    program = Program(ROOT)
    for prerequisite in ("framework_regression", "input_contract", "fixed_timestep"):
        require(program.check_state(prerequisite) == "verified",
                f"Current {prerequisite} evidence is required")
    framework = json.loads((program.evidence_dir / "framework_regression.json").read_text())
    junit = program.evidence_dir / "framework-pytest.xml"
    require(framework["started"] <= junit.stat().st_mtime <=
            framework["started"] + framework["duration_seconds"] + 2,
            "Python presentation JUnit is not from the verified framework run")
    suites = {
        "gfootball.frame_sync.test_render_interpolation.RenderInterpolationTest": 14,
        "gfootball.frame_sync.test_graphical_native.GraphicalNativeTest": 5,
        "gfootball.frame_sync.test_presentation_budget.HolderBudgetTest": 14,
        "gfootball.frame_sync.test_presentation_budget.RenderBudgetTest": 12,
        "gfootball.frame_sync.test_presentation_budget.LogicPresentationTest": 2,
        "gfootball.frame_sync.test_match_pause_ui.PauseCommandTest": 6,
        "gfootball.frame_sync.test_match_pause_ui.LocalPauseTest": 13,
        "gfootball.frame_sync.test_match_pause_ui.GraphicalPauseTest": 6,
    }
    tests = list(ET.parse(junit).getroot().iter("testcase"))
    selected = [case for case in tests if case.get("classname") in suites]
    require(len(selected) >= 72 and all(not any(case.find(kind) is not None
            for kind in ("failure", "error", "skipped")) for case in selected),
            "Python presentation or pause regression failed or skipped")
    for suite, minimum in suites.items():
        require(sum(case.get("classname") == suite for case in selected) >= minimum,
                f"Incomplete Python presentation suite: {suite}")

    input_record = json.loads((program.evidence_dir / "input_contract.json").read_text())
    input_line = json.loads((program.evidence_dir / input_record["log"]).read_text().splitlines()[-1])
    input_path = Path(input_line["artifact"]).resolve()
    require(input_path.is_relative_to(ROOT / ".project/optimization/benchmarks") and
            sha(input_path) == input_line["artifact_sha256"],
            "Current product window report is missing or changed")
    windows = json.loads(input_path.read_text())["windows"]["probe_result"]["cases"]
    require({row["kind"] for row in windows} == {"standalone", "tcp", "udp"},
            "Actual product display entries are incomplete")
    for row in windows:
        require(row["passed"] is True and row["actual_product_main"] is True and
                row["actual_xtest"] is True and row["renders"] >= 40 and
                row["match_swaps"] == row["renders"] and
                row["measurements"]["held_local_neutral"] == 0,
                f"Product {row['kind']} display, input or pause window failed")
        if row["kind"] != "standalone":
            measure = row["measurements"]
            require(all(measure["clearing_frames"].get(name, 0) >= 3 for name in
                        ("release", "focus_loss", "controls_paused", "resume_held_barrier")) and
                    measure["resume_repressed_frames"] >= 3,
                    f"Product {row['kind']} retained a stale key across pause")
    sys.path.insert(0, str(ROOT / ".project/checks"))
    from framework_regression import acceptance_python
    python = acceptance_python(None)
    cmake = subprocess.run([python, "-c", "import pybind11;print(pybind11.get_cmake_dir())"],
                           check=True, capture_output=True, text=True).stdout.strip()
    build = args.build.resolve()
    sources = {str(path.relative_to(ROOT)): sha(path) for pattern in (
        ".project/gates/presentation_smoothing.py", ".project/checks/render_pose_contract.py",
        ".project/quality.py", ".project/optimization/program.json",
        "engine/CMakeLists.txt", "engine/src/**/*.cpp", "engine/src/**/*.hpp",
        "engine/ai.cpp", "gfootball/frame_sync/*.py") for path in ROOT.glob(pattern) if path.is_file()}
    commands = []

    def run(argv, label, *, env=None, timeout=1800):
        log = output / (label + ".log")
        with log.open("wb") as stream:
            completed = subprocess.run([str(arg) for arg in argv], cwd=ROOT, env=env,
                                       stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        commands.append({"label": label, "argv": [str(arg) for arg in argv],
                         "returncode": completed.returncode, "log_sha256": sha(log)})
        require(completed.returncode == 0, f"{label} failed; see {log}")

    run(["cmake", "-S", ROOT / "engine", "-B", build, "-DCMAKE_BUILD_TYPE=Release",
         "-DBUILD_PYTHON_BINDINGS=ON", f"-DPython_EXECUTABLE={python}",
         f"-DPython_ROOT_DIR={python.parent.parent}", f"-Dpybind11_DIR={cmake}"], "configure")
    run(["cmake", "--build", build, "-j", "1", "--target", "game"], "build")
    package = output / "package/gfootball_engine"
    package.mkdir(parents=True)
    for source, target in ((build / "libgame.so", "_gameplayfootball.so"),
                           (build / "libfootball_engine.so", "libfootball_engine.so"),
                           (ROOT / "engine/__init__.py", "__init__.py")):
        require(source.is_file(), f"Missing current native binary: {source}")
        shutil.copy2(source, package / target)
    (package / "data").symlink_to(ROOT / "engine/data", target_is_directory=True)
    (package / "fonts").symlink_to(ROOT / "third_party/fonts", target_is_directory=True)
    environment = dict(os.environ, PYTHONPATH=str(output / "package") + os.pathsep + str(ROOT),
                       GFOOTBALL_DATA_DIR=str(package / "data"),
                       GFOOTBALL_FONT=str(package / "fonts/AlegreyaSansSC-ExtraBold.ttf"),
                       LIBGL_ALWAYS_SOFTWARE="1")
    for key in ("DISPLAY", "SDL_VIDEODRIVER", "LD_PRELOAD", "LD_LIBRARY_PATH"):
        environment.pop(key, None)
    run([python, __file__, "--worker", "--output", output / "worker"],
        "actual-correction", env=environment, timeout=300)
    run([python, ROOT / ".project/checks/render_pose_contract.py", "--build",
         "/tmp/football-optimization-native", "--output", output / "pose"],
        "actual-pose", timeout=900)
    for name, digest in sources.items():
        require(sha(ROOT / name) == digest, f"Source changed during presentation gate: {name}")
    child = json.loads((output / "worker/report.json").read_text())
    require(child["passed"] is True and child["assertions"] >= 20 and
            child["rollback_from_visible"] and child["inflight_retarget"] and
            child["paused_endpoint_stable"] and len(child["images"]) == 6,
            "Actual correction evidence is incomplete")
    pose = json.loads((output / "pose/report.json").read_text())
    require(pose["passed"] is True and pose["native_GameEnv_executed"] is True and
            pose["contract"]["assertions"] >= 200 and
            pose["contract"]["card_cases"] == 8 and len(pose["images"]) == 6,
            "Actual intermediate attachment pixels are incomplete")
    binary = {name: sha(package / name) for name in
              ("_gameplayfootball.so", "libfootball_engine.so")}
    assertions = child["assertions"] + pose["contract"]["assertions"] + len(selected) + len(windows)
    report = {"passed": True, "skipped": 0, "assertions": assertions,
              "actual_gameenv": True, "actual_pixels": True,
              "scope": "Real GameEnv rollback, retarget, intermediate attachment and paused pixels; product pause and input from current product windows",
              "sources": sources, "binaries": binary, "commands": commands,
              "correction": child, "pose": pose,
              "python_presentation_tests": len(selected),
              "framework_junit_sha256": sha(junit),
              "input_report_sha256": input_line["artifact_sha256"],
              "product_windows": {row["kind"]: row["renders"] for row in windows}}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "skipped": 0, "assertions": assertions,
                      "artifact": str(output / "report.json"),
                      "artifact_sha256": sha(output / "report.json")}), flush=True)


if __name__ == "__main__":
    main()
