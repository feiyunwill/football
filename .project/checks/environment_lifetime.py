#!/usr/bin/env python3
"""Exercise actual headless/EGL ownership, allocation leaks and failed startup."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from native_boundary import ROOT, require, run


def probe(binary, arguments, environment, minimum):
    print("Running lifecycle probe: " + " ".join(map(str, arguments)), flush=True)
    result = subprocess.run([str(binary), *map(str, arguments)], cwd=ROOT,
                            env=environment, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=180)
    print(result.stdout, flush=True)
    require(result.returncode == 0, f"Lifecycle probe exited {result.returncode}")
    reports = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"passed"')]
    require(len(reports) == 1, "Missing/ambiguous lifecycle report")
    report = reports[0]
    require(report.get("passed") is True and report.get("assertions", 0) >= minimum
            and report.get("skipped") == 0, "Incomplete lifecycle probe")
    return report


def broken_assets(destination, fragment):
    """Create an isolated overlay; never modify or copy the game's real assets."""
    assets = ROOT / "engine/data"
    destination.mkdir()
    for entry in assets.iterdir():
        if entry.name != "media":
            (destination / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
    media = destination / "media"
    media.mkdir()
    for entry in (assets / "media").iterdir():
        if entry.name != "shaders":
            (media / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
    shaders = media / "shaders"
    shaders.mkdir()
    for entry in (assets / "media/shaders").iterdir():
        if entry.name != "zphase.frag":
            (shaders / entry.name).symlink_to(entry)
    (shaders / "zphase.frag").write_text(fragment)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    args = parser.parse_args()
    build = args.build.resolve()
    run(["cmake", "-S", "engine", "-B", build, "-DBUILD_PYTHON_BINDINGS=ON"])
    run(["cmake", "--build", build, "-j", "1", "--target", "engine_lifetime_contract", "game"])
    binary = build / "bin/engine_lifetime_contract"
    environment = dict(os.environ)
    # This gate deliberately tests the EGL path, without opening a user window.
    environment.pop("DISPLAY", None)
    environment.pop("GFOOTBALL_DATA_DIR", None)
    environment.pop("GFOOTBALL_FONT", None)
    environment.pop("LD_PRELOAD", None)
    results = {"headless": probe(binary, [], environment, 167)}
    lsan = run(["c++", "-print-file-name=liblsan.so"], capture=True).strip()
    require(Path(lsan).is_file(), "LeakSanitizer runtime is unavailable")
    sanitized = dict(environment, LD_PRELOAD=lsan,
                     LSAN_OPTIONS="exitcode=23:report_objects=0")
    results["headless_lsan"] = probe(binary, [], sanitized, 167)
    # 2026-09-10: ten additional graphical invalid-reset invariants are mandatory.
    # results["egl_lsan"] = probe(binary, ["--render"], sanitized, 9)
    results["egl_lsan"] = probe(binary, ["--render"], sanitized, 19)
    with tempfile.TemporaryDirectory(prefix="football-failed-startup-") as directory:
        temporary = Path(directory)
        compile_failure = broken_assets(temporary / "compile", "#version 150\ninvalid shader syntax\n")
        link_failure = broken_assets(temporary / "link", """#version 150
uniform vec4 modelMatrix;
out vec4 stdout;
void main() { stdout = modelMatrix; }
""")
        results["startup_failure_lsan"] = probe(
            binary, ["--startup-failure", compile_failure, link_failure], sanitized, 11)
    results["python_binding"] = probe(sys.executable, ["-I", ROOT / ".project/checks/python_lifetime_probe.py",
                                                       # 2026-09-09: also verify pause/resume/finish exports.
                                                       # build / "libgame.so"], environment, 24)
                                                       # 2026-09-10: include six invalid-reset invariants per cycle.
                                                       # build / "libgame.so"], environment, 36)
                                                       build / "libgame.so"], environment, 60)
    print(json.dumps({"passed": True, "assertions": sum(r["assertions"] for r in results.values()),
                      "skipped": 0, "results": results,
                      "allocation_tracking": "standalone LeakSanitizer via LD_PRELOAD; no suppressions",
                      "graphics_scope": "real EGL contexts; renderer measured below; no GPU throughput claim"}))


if __name__ == "__main__":
    main()
