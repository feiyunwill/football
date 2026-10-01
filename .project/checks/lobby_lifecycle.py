#!/usr/bin/env python3
"""Verify canonical lobby wire bytes and real room-to-match lifecycle."""

import json
import os
import re
import shutil
import sys
import time

from network_reconnect import (ROOT, BENCHMARKS, NATIVE_BUILD, TEST_BUILD,
                               PACKAGE, acceptance_python, prepare_package,
                               require, run, sha256)


CPP_TESTS = 57
PYTHON_TESTS = 71
NATIVE_TESTS = 4
CPP_WITNESSES = (
    "LobbyProtocolTest.ExplicitFixedRoomWireLayoutAndZeroReservedBytes",
    "LobbyProtocolTest.PackStringRejectsLengthOverflow",
    "LobbyE2ETest.CreateJoinChatAndStartProductionRoom",
    "LobbyE2ETest.FinishedRoomIsRetiredAndSamePeersCanEnterAnotherMatch",
    "RoomManagerRegression.ValidatesCapacityAndStartAddress",
    "LobbyCapacity.UnidentifiedReservationExpiresButNamedConnectionSurvives",
)
PYTHON_WITNESSES = (
    "actual_host_join_end_ack_record_save_and_playback",
    "lobby_timeout_closes_all_owners_and_preserves_previous_recording",
    "tcp_natural_end_delivers_final_authority_ack_and_files",
    "udp_natural_end_delivers_final_authority_ack_and_files",
    "public_tcp_server_loop_closes_after_natural_end",
    "public_udp_server_loop_drains_and_closes_after_natural_end",
)
NATIVE_WITNESSES = (
    "test_multiplayer_native.NativeMultiplayerTest.test_gameenv_host_join_authority_end_and_native_recording",
    "test_match_completion_native.MatchCompletionNativeTest.test_real_gameenv_tcp_natural_end_and_ack",
    "test_match_completion_native.MatchCompletionNativeTest.test_real_gameenv_udp_natural_end_and_ack",
)


def unittest_count(log, minimum, witnesses):
    counts = re.findall(r"^Ran (\d+) tests? in ", log, re.MULTILINE)
    require(counts and int(counts[-1]) >= minimum and
            re.search(r"^OK$", log, re.MULTILINE),
            "Lobby Python suite incomplete or skipped")
    for witness in witnesses:
        require(re.search(rf"^test_.*{re.escape(witness)}.* \.\.\. ok$",
                          log, re.MULTILINE),
                f"Missing lobby lifecycle witness: {witness}")
    return int(counts[-1])


def main():
    require(sys.flags.optimize == 0, "Lobby gate needs enabled Python assertions")
    BENCHMARKS.mkdir(parents=True, exist_ok=True)
    output = BENCHMARKS / f"lobby-lifecycle-{time.time_ns()}"
    output.mkdir()
    commands = []

    run(output, commands, "configure-cpp",
        ["cmake", "-S", "engine/tests", "-B", TEST_BUILD,
         "-DCMAKE_BUILD_TYPE=Release"])
    run(output, commands, "build-cpp",
        ["cmake", "--build", TEST_BUILD, "-j", "1", "--target",
         "lobby_protocol_test", "room_manager_test", "lobby_e2e_test",
         "lobby_capacity_test", "lobby_client_capacity_test"], timeout=1200)
    cpp_log = run(output, commands, "cpp-lobby",
                  ["ctest", "--test-dir", TEST_BUILD, "-R",
                   r"^(LobbyProtocolTest|RoomManagerTest|RoomManagerRegression|LobbyE2ETest|LobbyCapacity|LobbyClientCapacity)\.",
                   "--output-on-failure", "-j", "1"], timeout=300)
    match = re.search(r"^100% tests passed out of (\d+)$", cpp_log,
                      re.MULTILINE)
    require(match and int(match.group(1)) >= CPP_TESTS and
            "Not Run" not in cpp_log and "Skipped" not in cpp_log,
            "C++ lobby suite incomplete or skipped")
    for witness in CPP_WITNESSES:
        require(witness in cpp_log, f"Missing C++ lobby witness: {witness}")
    cpp_tests = int(match.group(1))

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
            "Native Python engine and its core library are missing")
    binding = PACKAGE / "_gameplayfootball.so"
    if binding.is_symlink():
        binding.unlink()
    shutil.copy2(PACKAGE / "libgame.so", binding)
    native_env = os.environ.copy()
    native_env["PYTHONPATH"] = os.pathsep.join((str(NATIVE_BUILD / "package"),
                                                str(ROOT), native_env.get("PYTHONPATH", "")))

    python_log = run(output, commands, "python-lifecycle",
                     [python, "-m", "unittest", "-v",
                      "gfootball.frame_sync.lobby_test",
                      "gfootball.frame_sync.test_multiplayer",
                      "gfootball.frame_sync.test_match_lifecycle"],
                     timeout=600, env=native_env)
    python_tests = unittest_count(python_log, PYTHON_TESTS, PYTHON_WITNESSES)
    native_log = run(output, commands, "python-native-match",
                     [python, "-m", "unittest", "-v",
                      "gfootball.frame_sync.test_multiplayer_native",
                      "gfootball.frame_sync.test_match_completion_native"],
                     timeout=600, env=native_env)
    native_tests = unittest_count(native_log, NATIVE_TESTS, NATIVE_WITNESSES)

    report = {"passed": True,
              "assertions": cpp_tests + python_tests + native_tests,
              "skipped": 0, "cpp_tests": cpp_tests,
              "python_tests": python_tests, "native_tests": native_tests,
              "cpp_witnesses": CPP_WITNESSES,
              "python_witnesses": PYTHON_WITNESSES,
              "native_witnesses": NATIVE_WITNESSES,
              "commands": commands}
    artifact = output / "report.json"
    artifact.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "assertions": report["assertions"],
                      "skipped": 0, "artifact": str(artifact.relative_to(ROOT)),
                      "artifact_sha256": sha256(artifact)}), flush=True)


if __name__ == "__main__":
    main()
