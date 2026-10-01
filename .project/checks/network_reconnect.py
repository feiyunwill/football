#!/usr/bin/env python3
"""Exercise bounded reconnect and snapshot recovery over live transports."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / ".project/optimization/benchmarks"
NATIVE_BUILD = Path("/tmp/football-network-reconnect-bindings")
TEST_BUILD = Path("/tmp/football-optimization-tests")
PACKAGE = NATIVE_BUILD / "package/gfootball_engine"
PYTHON_TESTS = 135
CPP_TESTS = 26
MODULES = (
    "gfootball.frame_sync.test_reconnect_budget",
    "gfootball.frame_sync.test_tcp_client_budget",
    "gfootball.frame_sync.test_udp_resume_budget",
    "gfootball.frame_sync.test_udp_client_budget",
    "gfootball.frame_sync.test_server_budget",
)
PYTHON_WITNESSES = (
    "partial_snapshot_obeys_absolute_handshake_deadline_and_cleanup",
    "wire_token_automatic_restore_before_ready_and_contiguous_hashes",
    "repeated_disconnect_reclaims_old_workers_and_engine_stays_on_owner",
    "tick_does_not_wait_for_live_resume_handshake_and_close_cancels_it",
    "timestamp_eviction_is_bounded_diagnostics_and_rtt_uses_monotonic_time",
    "heartbeat_is_real_received_progress_independent_of_poll_frequency",
    "connection_cap_and_partial_handshake_timeout_release_real_sockets",
    "unacknowledged_session_is_bounded_and_expires",
    "expired_pending_restore_does_not_mutate_engine",
)
CPP_WITNESSES = (
    "TCPClientCapacity.PartialHandshakeHasAnAbsoluteDeadline",
    "TCPClientCapacity.ResumeRestoresOneBoundedSnapshotAndKeepsCoalescedFrames",
    "ReconnectingClient.EOFTriggersAutomaticSnapshotResumeAndConfirmedHashProgress",
    "ReconnectingClient.PartialResumeTimeoutRetriesTheSameSessionAndRestoresOnSecondAttempt",
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output, commands, name, argv, timeout=600, env=None):
    result = subprocess.run([str(value) for value in argv], cwd=ROOT,
                            env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    path = output / f"{name}.log"
    path.write_text(result.stdout)
    commands.append({"name": name, "argv": list(map(str, argv)),
                     "log": path.name, "sha256": sha256(path),
                     "returncode": result.returncode})
    require(result.returncode == 0,
            f"{name} exited {result.returncode}; see {path}")
    return result.stdout


def unittest_count(log, minimum, witnesses):
    counts = re.findall(r"^Ran (\d+) tests? in ", log, re.MULTILINE)
    require(counts and int(counts[-1]) >= minimum and
            re.search(r"^OK$", log, re.MULTILINE) and
            not re.search(r"^.* \.\.\. skipped ", log, re.MULTILINE),
            "Python reconnect suite incomplete or skipped")
    for witness in witnesses:
        require(re.search(rf"^test_{re.escape(witness)} .* \.\.\. ok$",
                          log, re.MULTILINE), f"Missing reconnect witness: {witness}")
    return int(counts[-1])


def prepare_package():
    PACKAGE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "engine/__init__.py", PACKAGE / "__init__.py")
    for name in ("data", "fonts"):
        target = PACKAGE / name
        if not target.exists():
            target.symlink_to(ROOT / "engine" / name, target_is_directory=True)
    binding = PACKAGE / "_gameplayfootball.so"
    if not binding.exists():
        binding.symlink_to("libgame.so")


def acceptance_python(output, commands):
    requirements = ROOT / ".project/checks/requirements.txt"
    identity = hashlib.sha256(requirements.read_bytes() +
                              sys.implementation.cache_tag.encode()).hexdigest()[:16]
    environment = Path(tempfile.gettempdir()) / f"football-framework-python-{identity}"
    python = environment / "bin/python"
    if not python.is_file():
        run(output, commands, "create-python", [sys.executable, "-m", "venv",
                                                environment])
    run(output, commands, "install-python",
        [python, "-m", "pip", "install", "--disable-pip-version-check",
         "-r", requirements], timeout=900)
    run(output, commands, "check-python", [python, "-m", "pip", "check"])
    return python


def main():
    require(sys.flags.optimize == 0, "Network gate needs enabled Python assertions")
    BENCHMARKS.mkdir(parents=True, exist_ok=True)
    output = BENCHMARKS / f"network-reconnect-{time.time_ns()}"
    output.mkdir()
    commands = []
    python = acceptance_python(output, commands)
    pybind11_dir = run(output, commands, "pybind11-dir",
                       [python, "-m", "pybind11", "--cmakedir"]).strip()

    python_log = run(output, commands, "python-transports",
                     [python, "-m", "unittest", "-v", *MODULES],
                     timeout=600)
    python_tests = unittest_count(python_log, PYTHON_TESTS, PYTHON_WITNESSES)

    prepare_package()
    run(output, commands, "configure-binding",
        ["cmake", "-S", "engine", "-B", NATIVE_BUILD,
         "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_PYTHON_BINDINGS=ON",
         f"-DPython_EXECUTABLE={python}",
         f"-Dpybind11_DIR={pybind11_dir}",
         f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={PACKAGE}"])
    run(output, commands, "build-binding",
        ["cmake", "--build", NATIVE_BUILD, "-j", "2", "--target", "game"],
        timeout=1800)
    require((PACKAGE / "libgame.so").is_file() and
            (PACKAGE / "libfootball_engine.so").is_file(),
            "Native Python engine and its core library are missing")
    native_env = os.environ.copy()
    native_env["PYTHONPATH"] = os.pathsep.join((str(NATIVE_BUILD / "package"),
                                                str(ROOT), native_env.get("PYTHONPATH", "")))
    native_log = run(output, commands, "python-native-resume",
                     [python, "-m", "unittest", "-v",
                      "gfootball.frame_sync.test_reconnect_native",
                      "gfootball.frame_sync.test_udp_resume_native"],
                     timeout=300, env=native_env)
    native_tests = unittest_count(native_log, 2, (
        "gameenv_automatic_token_snapshot_handback_and_thirteen_frames",))
    for identity in ("test_reconnect_native.ReconnectNativeTest",
                     "test_udp_resume_native.UDPResumeNativeTest"):
        require(identity in native_log, f"Missing native GameEnv recovery: {identity}")

    run(output, commands, "configure-cpp", ["cmake", "-S", "engine/tests",
                                             "-B", TEST_BUILD,
                                             "-DCMAKE_BUILD_TYPE=Release"])
    run(output, commands, "build-cpp",
        ["cmake", "--build", TEST_BUILD, "-j", "1",
         "--target", "tcp_client_capacity_test"], timeout=1200)
    ctest_log = run(output, commands, "cpp-reconnect",
                    ["ctest", "--test-dir", TEST_BUILD, "-R",
                     r"^(TCPClientCapacity|TCPFrameClient|ReconnectingClient)\.",
                     "--output-on-failure", "-j", "1"], timeout=300)
    match = re.search(r"^100% tests passed out of (\d+)$", ctest_log,
                      re.MULTILINE)
    require(match and int(match.group(1)) >= CPP_TESTS and
            "Not Run" not in ctest_log and "Skipped" not in ctest_log,
            "Native reconnect suite incomplete or skipped")
    for witness in CPP_WITNESSES:
        require(witness in ctest_log, f"Missing native witness: {witness}")
    cpp_tests = int(match.group(1))

    report = {"passed": True, "assertions": python_tests + native_tests + cpp_tests,
              "skipped": 0, "python_transport_tests": python_tests,
              "python_native_tests": native_tests, "cpp_tests": cpp_tests,
              "python_witnesses": PYTHON_WITNESSES,
              "cpp_witnesses": CPP_WITNESSES, "commands": commands}
    artifact = output / "report.json"
    artifact.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "assertions": report["assertions"],
                      "skipped": 0, "artifact": str(artifact.relative_to(ROOT)),
                      "artifact_sha256": sha256(artifact)}), flush=True)


if __name__ == "__main__":
    main()
