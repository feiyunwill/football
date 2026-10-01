#!/usr/bin/env python3
"""Native GameEnv, two real UDP peers, per-frame hashes and fault recovery."""

import json
import os
import re
import shutil
import sys
import time

from network_reconnect import (ROOT, BENCHMARKS, NATIVE_BUILD, PACKAGE,
                               acceptance_python, prepare_package, require,
                               run, sha256)


def count_tests(log, expected):
    match = re.search(r"^Ran (\d+) tests? in ", log, re.MULTILINE)
    require(match and int(match.group(1)) == expected and
            re.search(r"^OK$", log, re.MULTILINE) and
            not re.search(r"^.* \.\.\. skipped ", log, re.MULTILINE),
            f"Expected {expected} successful, unskipped network tests")


def main():
    require(sys.flags.optimize == 0, "Network gate needs enabled Python assertions")
    BENCHMARKS.mkdir(parents=True, exist_ok=True)
    output = BENCHMARKS / f"network-regression-{time.time_ns()}"
    output.mkdir()
    commands = []
    python = acceptance_python(output, commands)
    pybind11_dir = run(output, commands, "pybind11-dir",
                       [python, "-m", "pybind11", "--cmakedir"]).strip()
    prepare_package()
    run(output, commands, "configure-binding",
        ["cmake", "-S", "engine", "-B", NATIVE_BUILD,
         "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_PYTHON_BINDINGS=ON",
         f"-DPython_EXECUTABLE={python}", f"-Dpybind11_DIR={pybind11_dir}",
         f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={PACKAGE}"])
    run(output, commands, "build-binding",
        ["cmake", "--build", NATIVE_BUILD, "-j", "2", "--target", "game"],
        timeout=1800)
    require((PACKAGE / "libgame.so").is_file() and
            (PACKAGE / "libfootball_engine.so").is_file(),
            "Native GameEnv libraries are missing")
    binding = PACKAGE / "_gameplayfootball.so"
    if binding.is_symlink():
        binding.unlink()
    shutil.copy2(PACKAGE / "libgame.so", binding)
    native_env = os.environ.copy()
    native_env["PYTHONPATH"] = os.pathsep.join((str(NATIVE_BUILD / "package"),
                                                str(ROOT), native_env.get("PYTHONPATH", "")))

    matrix_log = run(output, commands, "two-peer-fault-matrix",
                     [python, "-m", "gfootball.frame_sync.test_network_regression_native"],
                     timeout=300, env=native_env)
    count_tests(matrix_log, 1)
    match = re.search(r"^NETWORK_MATRIX=(\{.*\})$", matrix_log, re.MULTILINE)
    require(match, "Native two-peer matrix did not publish measurements")
    matrix = json.loads(match.group(1))
    require(set(matrix) == {"baseline", "latency", "faults"},
            "Missing a network fault matrix mode")
    for mode, record in matrix.items():
        require(record["frames"] == 40 and record["peer_hash_checks"] == 80 and
                record["unique_inputs"] >= 4 and record["unique_digests"] >= 2,
                f"Two-client variable-input hash evidence incomplete: {mode}")
    for mode in ("latency", "faults"):
        record = matrix[mode]
        require(record["delayed"] > 0 and len(record["delay_ms"]) == 2 and
                record["delivered"] > 0 and record["maximum_datagram"] <= 1200,
                f"Latency/jitter injection incomplete: {mode}")
    require(all(matrix["faults"][name] > 0 for name in
                ("dropped", "duplicated", "reordered", "out_of_order")),
            "Loss, duplication and reordering were not all observed")

    recovery_log = run(output, commands, "disconnect-recovery",
                       [python, "-m", "unittest", "-v",
                        "gfootball.frame_sync.test_udp_resume_native.UDPResumeNativeTest.test_gameenv_automatic_token_snapshot_handback_and_thirteen_frames",
                        "gfootball.frame_sync.test_multiplayer_udp.MultiplayerUDPTest.test_running_client_only_loss_recovers_original_token_engine_and_new_epoch"],
                       timeout=300, env=native_env)
    count_tests(recovery_log, 2)
    for witness in ("automatic_token_snapshot_handback_and_thirteen_frames",
                    "running_client_only_loss_recovers_original_token_engine_and_new_epoch"):
        require(re.search(rf"^test_.*{witness} .* \.\.\. ok$", recovery_log, re.MULTILINE),
                f"Missing disconnect recovery witness: {witness}")

    report = {"passed": True, "assertions": 242, "skipped": 0,
              "matrix": matrix, "disconnect_tests": 2, "commands": commands,
              "scope": "Python UDP product transport; native GameEnv hash replica; "
                       "disconnect includes one native and one two-peer oracle test"}
    artifact = output / "report.json"
    artifact.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "assertions": report["assertions"],
                      "skipped": 0, "artifact": str(artifact.relative_to(ROOT)),
                      "artifact_sha256": sha256(artifact)}), flush=True)


if __name__ == "__main__":
    main()
