#!/usr/bin/env python3
"""2026-09-13: reproducible input/history/log/send-queue capacity acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from framework_regression import junit_count
from integrated_tcp_probe import environment as native_environment
from match_benchmark import source_manifest
from native_boundary import ROOT, require

UNIT_TARGETS = {
    "reliable_udp_budget_test": 12,
    "bounded_tcp_writer_test": 10,
    "lobby_capacity_test": 10,
    "lobby_client_capacity_test": 10,
    "tcp_frame_server_test": 8,
    "tcp_client_capacity_test": 26,
}
MARKERS = ("ERROR: AddressSanitizer", "ERROR: LeakSanitizer", "runtime error:",
           "AddressSanitizer:DEADLYSIGNAL", "SUMMARY: UndefinedBehaviorSanitizer")


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(65536):
            digest.update(block)
    return digest.hexdigest()


def inputs():
    result = source_manifest()
    # The common native manifest deliberately omits some Python adapters.
    # Capacity acceptance also owns their implementation and recording tests.
    for pattern in ("gfootball/**/*.py", "engine/frame_sync_asio/CMakeLists.txt",
                    "pyproject.toml", "requirements.txt", "engine/__init__.py",
                    ".project/optimization/capacity-contract.md"):
        paths = [path for path in ROOT.glob(pattern) if path.is_file()]
        require(paths, f"Empty capacity source scope: {pattern}")
        for path in paths:
            require(path.resolve().is_relative_to(ROOT), "Capacity source escapes checkout")
            result[path.relative_to(ROOT).as_posix()] = sha(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    require(platform.system() == "Linux", "Native capacity acceptance requires Linux")
    # 2026-09-13: several maintained protocol probes use Python assert.
    # Reject parent flags and child-inherited settings that would disable them.
    require(sys.flags.optimize == 0 and os.environ.get("PYTHONOPTIMIZE", "") in ("", "0"),
            "Capacity acceptance requires Python assertions enabled")
    output = (args.output or ROOT / f".project/optimization/benchmarks/memory-budget-{time.time_ns()}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    original = inputs()
    # Preserve the original inputs even when a later scenario fails.
    (output / "sources.json").write_text(json.dumps(original, indent=2) + "\n")
    commands, cases, binaries = [], [], {}
    environment = dict(os.environ, ASAN_OPTIONS="halt_on_error=1:detect_leaks=1:quarantine_size_mb=16",
                       UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1", LSAN_OPTIONS="exitcode=23")
    environment.pop("LD_PRELOAD", None)

    def run(argv, name, *, env=None, timeout=600):
        argv = list(map(str, argv))
        log = output / (name + ".log")
        started = time.monotonic()
        timed_out = False
        with log.open("w") as stream:
            process = subprocess.Popen(argv, cwd=ROOT, env=env or environment,
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # Own session, unreaped leader: terminate all of this check's children.
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            except BaseException:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                raise
        row = dict(argv=argv, returncode=process.returncode, timed_out=timed_out, log=log.name,
                   log_sha256=sha(log), seconds=time.monotonic() - started)
        commands.append(row)
        (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        text = log.read_text()
        require(not timed_out and process.returncode == 0 and not any(marker in text for marker in MARKERS),
                f"Capacity command failed: {log}")
        return text

    def pin(label, path):
        binaries[label] = dict(path=str(path), sha256=sha(path))
        (output / "binaries.json").write_text(json.dumps(binaries, indent=2) + "\n")

    def group(label, script, arguments, count, *, env=None):
        destination = output / label
        run([sys.executable, ROOT / ".project/checks" / script, *arguments, "--output", destination],
            label, env=env, timeout=600)
        path = destination / "report.json"
        report = json.loads(path.read_text())
        rows = report.get("cases", [])
        require(report.get("passed") is True and not report.get("skipped", 0) and
                len(rows) == count and all(row.get("passed") is True and not row.get("forced_cleanup") for row in rows),
                f"Missing or failed capacity scenarios: {label}")
        cases.append(dict(name=label, executions=count, report=str(path.relative_to(output)), sha256=sha(path)))

    cached = Path("/tmp/football-review-20260909-tests/_deps/googletest-src")
    require(cached.is_dir(), "Documented local GoogleTest source is required")
    ordinary = Path("/tmp/football-optimization-native")
    native_targets = ("football_client", "football_server", "football_client_tcp", "football_server_tcp",
                      "engine_runtime_contract", "engine_tcp_contract", "engine_tcp_client_contract", "engine_memory_contract")
    import pybind11
    for label, tests, build, standalone, sanitizer in (
            ("ordinary", Path("/tmp/football-optimization-tests"), ordinary,
             Path("/tmp/football-optimization-memory-asio-release"), False),
            ("sanitized", Path("/tmp/football-optimization-query-tests"), Path("/tmp/football-optimization-sanitized"),
             Path("/tmp/football-optimization-memory-asio"), True)):
        mode = "ON" if sanitizer else "OFF"
        run(["cmake", "-S", "engine/tests", "-B", tests, "-DCMAKE_BUILD_TYPE=Debug", "-DENABLE_PCH=OFF",
             f"-DENABLE_ASAN={mode}", f"-DENABLE_UBSAN={mode}", "-DENABLE_TSAN=OFF",
             "-DENABLE_PERFORMANCE_TESTS=OFF", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
             f"-DFETCHCONTENT_SOURCE_DIR_GOOGLETEST={cached}"], label + "-configure-tests")
        run(["cmake", "--build", tests, "-j", "1", "--target", *UNIT_TARGETS], label + "-build-tests", timeout=1200)
        for target, minimum in UNIT_TARGETS.items():
            dynamic = run(["readelf", "-d", tests / target], label + "-" + target + "-dependencies")
            require(("libasan" in dynamic) == sanitizer and ("libubsan" in dynamic) == sanitizer,
                    "Unit binary has the wrong detector configuration")
            path = output / f"{label}-{target}.json"
            run([tests / target, "--gtest_filter=-PerformanceTest.*", f"--gtest_output=json:{path}"],
                label + "-" + target, timeout=180)
            report = json.loads(path.read_text())
            rows = [case for suite in report["testsuites"] for case in suite["testsuite"]]
            require(report["tests"] >= minimum and len(rows) == report["tests"] and
                    not any(report.get(key, 0) for key in ("failures", "errors", "disabled")) and
                    all(row["status"] == "RUN" and row["result"] == "COMPLETED" for row in rows),
                    f"Missing/skipped/failing bounded transport tests: {target}")
            cases.append(dict(name=label + "/" + target, executions=len(rows), report=path.name, sha256=sha(path)))
            pin(label + "/" + target, tests / target)

        configuration = ["cmake", "-S", "engine", "-B", build,
                         "-DCMAKE_BUILD_TYPE=" + ("Debug" if sanitizer else "Release"),
                         f"-DFOOTBALL_ENABLE_SANITIZERS={mode}", "-DBUILD_PYTHON_BINDINGS=" + ("OFF" if sanitizer else "ON"),
                         f"-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / 'bin'}"]
        if not sanitizer:
            configuration += [f"-DPython_EXECUTABLE={sys.executable}", f"-DPython_ROOT_DIR={sys.prefix}",
                              f"-Dpybind11_DIR={pybind11.get_cmake_dir()}"]
        run(configuration, label + "-configure-native")
        compilation = json.loads((build / "compile_commands.json").read_text())
        require(len(compilation) >= 100, "Capacity check needs the full native engine")
        for entry in compilation:
            flags = entry["command"]
            require(("-fsanitize=address,undefined" in flags) == sanitizer, "Native instrumentation differs across units")
            if sanitizer:
                require("-fno-sanitize-recover=all" in flags and "-fno-omit-frame-pointer" in flags,
                        "Incomplete full-engine detector flags")
        run(["cmake", "--build", build, "-j", "1", "--target", *native_targets,
             *(["game"] if not sanitizer else [])], label + "-build-native", timeout=1800)
        dynamic = run(["readelf", "-d", build / "libfootball_engine.so"], label + "-native-dependencies")
        require(("libasan" in dynamic) == sanitizer and ("libubsan" in dynamic) == sanitizer,
                "Native engine has the wrong detector configuration")
        for target in native_targets:
            pin(label + "/native/" + target, build / "bin" / target)
        pin(label + "/core", build / "libfootball_engine.so")
        group(label + "-runtime", "runtime_capacity_probe.py", ["--build", build], 4)
        text = run([build / "bin/engine_tcp_contract"], label + "-native-tcp-server",
                   env=native_environment(build), timeout=180)
        summaries = [json.loads(line) for line in text.splitlines() if line.startswith('{"passed"')]
        require(len(summaries) == 1, "Missing/ambiguous actual native server contract")
        summary = summaries[0]
        require(summary["passed"] and not summary["skipped"] and summary["confirmed_frames"] >= 40 and
                summary["hashes_checked"] >= 8 and 0 < summary["reconnect_snapshot_bytes"] <= 1024 * 1024,
                "Actual GameEnv capacity/slow-peer/reconnect contract is incomplete")
        cases.append(dict(name=label + "/native-tcp-server", executions=1, contract=summary))
        group(label + "-tcp-resume", "engine_tcp_client_probe.py", ["--build", build], 2)
        group(label + "-integrated-tcp", "integrated_tcp_probe.py", ["--build", build], 11)
        group(label + "-udp-faults", "udp_capacity_probe.py", ["--build", build], 4)
        group(label + "-udp-pair", "udp_capacity_probe.py", ["--build", build, "--pair-only"], 1)

        flags = "-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer" if sanitizer else ""
        run(["cmake", "-S", "engine/frame_sync_asio", "-B", standalone,
             "-DCMAKE_BUILD_TYPE=" + ("Debug" if sanitizer else "Release"),
             f"-DCMAKE_CXX_FLAGS={flags}", f"-DCMAKE_EXE_LINKER_FLAGS={flags}"], label + "-configure-standalone")
        run(["cmake", "--build", standalone, "-j", "1", "--target", "frame_sync_server", "frame_sync_client"],
            label + "-build-standalone")
        for target in ("frame_sync_server", "frame_sync_client"):
            dynamic = run(["readelf", "-d", standalone / target], label + "-" + target + "-dependencies")
            require(("libasan" in dynamic) == sanitizer and ("libubsan" in dynamic) == sanitizer,
                    "Standalone networking has the wrong detector configuration")
            pin(label + "/standalone/" + target, standalone / target)
        group(label + "-standalone-server", "tcp_capacity_probe.py", ["--server", standalone / "frame_sync_server"], 7)
        group(label + "-standalone-client", "tcp_client_probe.py",
              ["--server", standalone / "frame_sync_server", "--client", standalone / "frame_sync_client"], 11)

    # Run the maintained native persistence checker, including the maximum recording,
    # directory quotas, killed writer and actual paired clients, without old evidence reuse.
    replay = output / "replay"
    run([sys.executable, ROOT / ".project/checks/replay_persistence.py", "--output", replay],
        "replay", timeout=1800)
    replay_report = json.loads((replay / "report.json").read_text())
    require(replay_report["passed"] and not replay_report["skipped"] and replay_report["unit_cases"] >= 208 and
            # 2026-09-13: retain abrupt EOF and add a fixed-boundary real pair in each build.
            # replay_report["native_cases"] == 14, "Incomplete native replay and storage coverage")
            replay_report["native_cases"] == 16, "Incomplete native replay and storage coverage")
    cases.append(dict(name="native-replay", executions=replay_report["unit_cases"] + replay_report["native_cases"],
                      report="replay/report.json", sha256=sha(replay / "report.json")))
    for name, value in replay_report["binaries"].items():
        binaries["replay/" + name] = value

    # Current native package, independent of whichever older wheel supplies Python dependencies.
    with tempfile.TemporaryDirectory(prefix="football-capacity-python-") as directory:
        staging = Path(directory)
        package = staging / "gfootball_engine"; package.mkdir()
        for source, target in ((ordinary / "libgame.so", "_gameplayfootball.so"),
                               (ordinary / "libfootball_engine.so", "libfootball_engine.so"),
                               (ROOT / "engine/__init__.py", "__init__.py")):
            shutil.copy2(source, package / target)
        (package / "data").symlink_to(ROOT / "engine/data", target_is_directory=True)
        (package / "fonts").symlink_to(ROOT / "third_party/fonts", target_is_directory=True)
        env = native_environment(ordinary)
        env.pop("LD_LIBRARY_PATH", None)
        # 2026-09-13: the full Python suite requires an actual SDL event/window
        # context; the separate native runtime probe above still covers EGL.
        # env.update(PYTHONPATH=str(staging) + os.pathsep + str(ROOT),
        env.update(DISPLAY=":football-test", SDL_VIDEODRIVER="offscreen",
                   PYTHONPATH=str(staging) + os.pathsep + str(ROOT),
                   GFOOTBALL_DATA_DIR=str(package / "data"),
                   GFOOTBALL_FONT=str(package / "fonts/AlegreyaSansSC-ExtraBold.ttf"))
        code = ("import sys,json;sys.path.insert(0,sys.argv[1]);"
                "from native_runtime_identity import native_runtime_identity;"
                "print(json.dumps(native_runtime_identity(sys.argv[2])))")
        identity = json.loads(run([sys.executable, "-c", code, ROOT / ".project/checks", ROOT],
                                  "python-native-identity", env=env))
        require(Path(identity["binding"]).parent == package and Path(identity["engine"]).parent == package and
                identity["binding_sha256"] == sha(ordinary / "libgame.so") and
                identity["engine_sha256"] == sha(ordinary / "libfootball_engine.so"),
                "Python capacity suites would exercise a different native engine")
        junit = output / "python-frame-sync.xml"
        run([sys.executable, "-m", "pytest", "gfootball/frame_sync", "-q",
             "--ignore=gfootball/frame_sync/legacy_network_test.py", f"--junitxml={junit}"],
            "python-frame-sync", env=env, timeout=600)
        cases.append(dict(name="python-frame-sync", executions=junit_count(junit, 758), report=junit.name, sha256=sha(junit)))
        recording = output / "python-recording"
        run([sys.executable, ROOT / ".project/checks/python_recording_probe.py", "--output", recording,
             "--environment", "--replay", "--native", "--rendering"], "python-recording", env=env, timeout=240)
        report = json.loads((recording / "report.json").read_text())
        require(report["passed"] and report["tests"] >= 174 and not report["skipped"] and
                report["native_GameEnv_suite_passed"] and report["renderer_suite_passed"] and
                report["native_runtime"]["binding_sha256"] == identity["binding_sha256"] and
                report["native_runtime"]["engine_sha256"] == identity["engine_sha256"],
                "Incomplete actual Python environment/recording/resource recovery")
        cases.append(dict(name="python-recording", executions=report["tests"],
                          report="python-recording/report.json", sha256=sha(recording / "report.json")))
        pin("python/binding", ordinary / "libgame.so")

    require(original == inputs(), "Capacity inputs changed during verification")
    require(all(sha(Path(value["path"])) == value["sha256"] for value in binaries.values()),
            "Exercised native binary changed during verification")
    artifacts = {path.relative_to(output).as_posix(): dict(bytes=path.stat().st_size, sha256=sha(path))
                 for path in sorted(output.rglob("*")) if path.is_file()}
    report = dict(passed=True, skipped=0, assertions=sum(row["executions"] for row in cases),
                  cases=cases, sources=original, binaries=binaries, artifacts=artifacts, commands=commands,
                  native_python_identity=identity, platform=platform.platform(), python=sys.version,
                  scope="task-21.1.2.1 input/history/log/send-queue capacity and reproducible overload/recovery; "
                        "case counts are executions across distinct configurations, not unique tests; "
                        "excludes full-process RSS/GPU bytes, WAN/authentication/interop and product input-feel acceptance")
    destination = output / "report.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(passed=True, skipped=0, assertions=report["assertions"],
                          artifact=str(destination), artifact_sha256=sha(destination))))


if __name__ == "__main__":
    main()
