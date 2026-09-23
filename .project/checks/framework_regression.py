#!/usr/bin/env python3
"""Configuration contracts, complete local unit suites, and native determinism."""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
import shlex
import sys
import xml.etree.ElementTree as ET

from native_boundary import ROOT, require, run


# 2026-09-24: explicit transport suite coverage prevents silent CMake omissions.
NATIVE_UDP_SUITES = {
    "native_udp_bootstrap_test.": 28,
    "native_udp_window_test.": 37,
    "native_udp_stream_test.": 27,
    "native_udp_listener_test.": 20,
    "native_udp_dialer_test.": 24,
    "native_udp_terminal_drain_test.": 6,
}


REQUIRED_CPP_SUITES = {**NATIVE_UDP_SUITES, "rl_observation_contract": 1,
                       "native_input_rtt_test.": 8}

# Previous implementation preserved in native-udp-acceptance-inputs-20260924-a/originals.
def junit_count(path, minimum, required_suites=None):
    tree = ET.parse(path)
    cases = list(tree.iter("testcase"))
    require(len(cases) >= minimum, f"Only {len(cases)} cases, expected at least {minimum}: {path}")
    require(not any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")),
            f"Failure, error or skipped test in {path}")
    if required_suites:
        names = [case.get("name", "") for case in cases]
        require(all(names) and len(set(names)) == len(names),
                f"Missing or duplicate test identity in {path}")
        for prefix, required in required_suites.items():
            actual = sum(name.startswith(prefix) for name in names)
            require(actual >= required,
                    f"Incomplete suite {prefix}: {actual}, expected at least {required}: {path}")
    return len(cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-build", type=Path, default=Path("/tmp/football-optimization-native"))
    parser.add_argument("--tests-build", type=Path, default=Path("/tmp/football-optimization-tests"))
    parser.add_argument("--python", type=Path)
    args = parser.parse_args()
    native, tests = args.native_build.resolve(), args.tests_build.resolve()
    # Debug must remain debuggable regardless of native/Python build selection.
    debug = native.parent / (native.name + "-debug-config")
    run(["cmake", "-S", "engine", "-B", debug, "-DCMAKE_BUILD_TYPE=Debug", "-DBUILD_PYTHON_BINDINGS=OFF",
         f"-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={debug / 'bin'}"])
    commands = json.loads((debug / "compile_commands.json").read_text())
    require(len(commands) >= 100, "Debug configuration did not include the real engine")
    for entry in commands:
        flags = shlex.split(entry["command"])
        require("-g" in flags and not any(flag in flags for flag in ("-O2", "-O3", "-Ofast", "-DNDEBUG")),
                f"Debug configuration overridden: {entry['file']}")
    run(["cmake", "-S", "engine/tests", "-B", tests, "-DCMAKE_BUILD_TYPE=Debug", "-DENABLE_PCH=OFF"])
    run(["cmake", "--build", tests, "-j", "1"])
    reports = ROOT / ".project/optimization/evidence"
    reports.mkdir(parents=True, exist_ok=True)
    cpp_report = reports / "framework-ctest.xml"
    run(["ctest", "--test-dir", tests, "--output-on-failure", "--output-junit", cpp_report])
    # 560 existing + 142 UDP + observation layout + 8 input lead/cadence contracts.
    cpp_count = junit_count(cpp_report, 711, REQUIRED_CPP_SUITES)
    # 2026-09-22: permanently run the actual shared-engine asset parser contracts.
    run(["cmake", "--build", native, "--target", "engine_ase_parser_contract", "-j", "1"])
    asset_parser = json.loads(run([native / "bin/engine_ase_parser_contract"], capture=True))
    require(asset_parser.get("passed") is True and asset_parser.get("checks") == 10
            and asset_parser.get("skipped") == 0 and asset_parser.get("assertions", 0) > 0,
            "Incomplete native ASE parser coverage")
    # 2026-09-22: real resource reader coverage, including block boundaries and errors.
    run(["cmake", "--build", native, "--target", "engine_file_read_contract", "-j", "1"])
    file_reader = json.loads(run([native / "bin/engine_file_read_contract"], capture=True))
    require(file_reader.get("passed") is True and file_reader.get("checks") == 14
            and file_reader.get("skipped") == 0 and file_reader.get("assertions", 0) > 0,
            "Incomplete native file reader coverage")
    # 2026-09-10: use the current installed gate environment, without mutating an old Gym venv.
    # python = args.python
    # if python is None:
    # environment = Path("/tmp/football-optimization-python")
    # python = environment / "bin/python"
    # if not python.exists():
    # run([sys.executable, "-m", "venv", environment])
    # run([python, "-m", "pip", "install", "-r", ".project/checks/requirements.txt"])
    # # Do not resolve a venv Python symlink: that would select the system prefix.
    # if args.python:
    # python = args.python.absolute()
    # else:
    # python = environment / "bin/python"
    python = args.python.absolute() if args.python else Path(sys.executable)
    python_report = reports / "framework-pytest.xml"
    # 2026-09-10: use the binding built for this source revision, not an older installed wheel.
    # run([python, "-m", "pytest", "gfootball/frame_sync", "-q",
    #      "--ignore=gfootball/frame_sync/legacy_network_test.py", f"--junitxml={python_report}"])
    with tempfile.TemporaryDirectory(prefix="football-framework-python-") as directory:
        staging = Path(directory)
        package = staging / "gfootball_engine"
        package.mkdir()
        for source, target in ((native / "libgame.so", "_gameplayfootball.so"),
                               (native / "libfootball_engine.so", "libfootball_engine.so"),
                               (ROOT / "engine/__init__.py", "__init__.py")):
            shutil.copy2(source, package / target)
        (package / "data").symlink_to(ROOT / "engine/data", target_is_directory=True)
        (package / "fonts").symlink_to(ROOT / "third_party/fonts", target_is_directory=True)
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(staging) + os.pathsep + str(ROOT)
        # Deterministic resource selection for this source checkout.
        environment["GFOOTBALL_DATA_DIR"] = str(package / "data")
        environment["GFOOTBALL_FONT"] = str(package / "fonts/AlegreyaSansSC-ExtraBold.ttf")
        identity_probe = """
import hashlib, json
from pathlib import Path
import gfootball_engine
import gfootball_engine._gameplayfootball as native
paths = dict(loader=Path(gfootball_engine.__file__),
             binding=Path(native.__file__),
             engine=Path(gfootball_engine.__file__).parent/'libfootball_engine.so')
print(json.dumps({key:dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                  for key,path in paths.items()}))
"""
        native_identity = json.loads(run([python, "-c", identity_probe], capture=True, env=environment))
        run([python, "-m", "pytest", "gfootball/frame_sync", "-q",
             "--ignore=gfootball/frame_sync/legacy_network_test.py", f"--junitxml={python_report}"],
            env=environment)

    python_count = junit_count(python_report, 165)
    # The legacy network adapter explicitly belongs to ms-23.1; it is not
    # included or counted as passed by this local unit-test gate.
    native_output = run([python, "engine/tests/run_headless_regression.py", native / "bin/headless_match",
                         "--frames", "1000"], capture=True)
    results = json.loads(native_output)
    require(len(results) == 2 and all(item["frames"] == 1000 and item["independent_processes"] == 2
                                    and item["snapshot_replay"] for item in results),
            "Incomplete native process/snapshot coverage")
    # 2026-09-22: retain previous assertion accounting and add native parser checks.
    # print(json.dumps({"passed": True, "assertions": cpp_count + python_count + 3, "skipped": 0,
    # 2026-09-22: retain prior accounting and include file-read contracts.
    # print(json.dumps({"passed": True, "assertions": cpp_count + python_count + 3 + asset_parser["assertions"], "skipped": 0,
    print(json.dumps({"passed": True, "assertions": cpp_count + python_count + 3 + asset_parser["assertions"] + file_reader["assertions"], "skipped": 0,
                      "native_file_reader": file_reader,
                      "native_asset_parser": asset_parser,
                      "cpp_tests": cpp_count, "python_tests": python_count,
                      "native_udp_required_suites": NATIVE_UDP_SUITES,
                      "required_cpp_suites": REQUIRED_CPP_SUITES,
                      "debug_compilation_units": len(commands), "native_determinism": results,
                      "python_executable": str(python), "python_native_runtime": native_identity,
                      "network_integration": "separate required milestone ms-23.1"}))


if __name__ == "__main__":
    main()
