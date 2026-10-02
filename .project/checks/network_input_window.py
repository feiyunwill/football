#!/usr/bin/env python3
"""Verify bounded authoritative input on native and live socket paths."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / ".project/optimization/benchmarks"
NATIVE_BUILD = Path("/tmp/football-optimization-native")
TEST_BUILD = Path("/tmp/football-optimization-tests")
NATIVE_ASSERTIONS = 552018
SERVER_TESTS = 32
UDP_TESTS = 27
NATIVE_SOCKET_TESTS = 37


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(output, name, argv, timeout=600):
    result = subprocess.run([str(value) for value in argv], cwd=ROOT,
                            text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    path = output / f"{name}.log"
    path.write_text(result.stdout)
    require(result.returncode == 0,
            f"{name} exited {result.returncode}; see {path}")
    return result.stdout, {"name": name, "argv": list(map(str, argv)),
                           "log": path.name, "sha256": sha256(path)}


def unittest_count(log, minimum, witnesses):
    counts = re.findall(r"^Ran (\d+) tests? in ", log, re.MULTILINE)
    require(counts and int(counts[-1]) >= minimum and
            re.search(r"^OK$", log, re.MULTILINE),
            "Unittest suite did not finish with the required tests")
    for witness in witnesses:
        require(re.search(rf"^test_{re.escape(witness)} .* \.\.\. ok$",
                          log, re.MULTILINE),
                f"Missing live socket witness: {witness}")
    return int(counts[-1])


def main():
    require(sys.flags.optimize == 0, "Network gate needs enabled Python assertions")
    BENCHMARKS.mkdir(parents=True, exist_ok=True)
    output = BENCHMARKS / f"network-input-window-{time.time_ns()}"
    output.mkdir()
    commands = []

    def run(name, argv, timeout=600):
        log, record = command(output, name, argv, timeout)
        commands.append(record)
        return log

    run("configure-native", ["cmake", "-S", "engine", "-B", NATIVE_BUILD,
                             "-DCMAKE_BUILD_TYPE=Release",
                             "-DBUILD_PYTHON_BINDINGS=OFF",
                             f"-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={NATIVE_BUILD / 'bin'}"])
    run("build-native", ["cmake", "--build", NATIVE_BUILD, "-j", "1",
                         "--target", "engine_server_input_window_contract"])
    native = json.loads(run("native-window", [NATIVE_BUILD /
                            "bin/engine_server_input_window_contract"]).strip().splitlines()[-1])
    require(native.get("passed") is True and native.get("skipped") == 0 and
            native.get("assertions", 0) >= NATIVE_ASSERTIONS and
            native.get("frames", 0) >= 18000 and
            native.get("fixed_bytes", 0) <= 4096,
            "Native ring window contract is incomplete")

    server_log = run("server-budget", [sys.executable, "-m", "unittest", "-v",
                                       "gfootball.frame_sync.test_server_budget"])
    server_tests = unittest_count(server_log, SERVER_TESTS, (
        "twenty_two_real_clients_share_one_bounded_future_window",
        "actual_slow_reader_hits_write_deadline_and_server_stays_responsive",
        "oversized_header_and_invalid_owned_input_close_without_entering_engine",
    ))
    udp_log = run("udp-budget", [sys.executable, "-m", "unittest", "-v",
                                    "gfootball.frame_sync.test_udp_budget"])
    udp_tests = unittest_count(udp_log, UDP_TESTS, (
        "real_bidirectional_loss_duplicate_reorder_and_complete_refund",
        "source_filter_does_not_ack_or_deliver_foreign_data",
    ))

    run("configure-native-sockets", ["cmake", "-S", "engine/tests", "-B",
                                     TEST_BUILD, "-DCMAKE_BUILD_TYPE=Release"])
    run("build-native-sockets", ["cmake", "--build", TEST_BUILD, "-j", "1",
                                   "--target", "tcp_frame_server_test",
                                   "native_udp_window_test",
                                   "bounded_tcp_writer_test",
                                   "reliable_udp_budget_test"], timeout=1200)
    ctest_log = run("native-sockets", ["ctest", "--test-dir", TEST_BUILD, "-R",
                                       r"^(tcp_frame_server_test|native_udp_window_test|bounded_tcp_writer_test|reliable_udp_budget_test)\.",
                                       "--output-on-failure", "-j", "1"])
    match = re.search(r"^100% tests passed out of (\d+)$", ctest_log, re.MULTILINE)
    require(match and int(match.group(1)) >= NATIVE_SOCKET_TESTS and
            "Not Run" not in ctest_log and "Skipped" not in ctest_log,
            "Native TCP/UDP socket suite is incomplete")
    socket_tests = int(match.group(1))

    report = {"passed": True, "assertions": native["assertions"] + server_tests +
              udp_tests + socket_tests, "skipped": 0,
              "native_window": native, "server_tests": server_tests,
              "udp_tests": udp_tests, "native_socket_tests": socket_tests,
              "actual_tcp_backpressure": True, "actual_22_client_window": True,
              "actual_udp_loss_duplicate_reorder": True, "commands": commands}
    artifact = output / "report.json"
    artifact.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "assertions": report["assertions"],
                      "skipped": 0, "artifact": str(artifact.relative_to(ROOT)),
                      "artifact_sha256": sha256(artifact),
                      "native_socket_tests": socket_tests}), flush=True)


if __name__ == "__main__":
    main()
