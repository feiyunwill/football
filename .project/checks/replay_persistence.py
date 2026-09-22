#!/usr/bin/env python3
"""Native replay persistence contract; does not award the full memory milestone."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

from native_boundary import ROOT, require
from match_benchmark import source_manifest


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_replay(path, *, maximum=False):
    """Independent streaming decoder of the existing little-endian C++ format."""
    size = path.stat().st_size
    require(0 < size <= 32 * 1024 * 1024, "Invalid native replay file size")
    input_limit = struct.unpack("<f", struct.pack("<f", 1.001))[0]
    with path.open("rb") as stream:
        def exact(count):
            value = stream.read(count)
            require(len(value) == count, "Truncated native replay file")
            return value
        seed, scenario_length = struct.unpack("<II", exact(8))
        require(scenario_length <= 1024, "Unbounded replay scenario")
        scenario = exact(scenario_length).decode("utf-8")
        count, slots, final_hash, repeated_count = struct.unpack("<IIQI", exact(20))
        require(count == repeated_count and 0 < count <= 100000 and 1 <= slots <= 22,
                "Invalid replay shape")
        require(size == 28 + scenario_length + count * (12 + slots * 10), "Trailing or missing replay bytes")
        if maximum:
            require((seed, scenario, count, slots) == (42, "streamed_native_replay", 100000, 22),
                    "Maximum replay fixture changed")
        previous = -1
        for index in range(count):
            frame, state_hash = struct.unpack("<IQ", exact(12))
            require(frame > previous, "Replay frames lost order")
            previous = frame
            if maximum:
                expected_hash = ((index * 0x9E3779B97F4A7C15) & ((1 << 64) - 1)) ^ 42
                require(frame == index and state_hash == expected_hash, "Maximum replay lost a frame/hash")
            for slot in range(slots):
                x, y, buttons = struct.unpack("<ffH", exact(10))
                # 2026-09-10: match protocol.hpp's float32 tolerance and twelve button bits.
                # require(-1 <= x <= 1 and -1 <= y <= 1 and buttons < (1 << 14), "Invalid saved input")
                # 2026-09-10: compute the fixed protocol bound once per file.
                # limit = struct.unpack("<f", struct.pack("<f", 1.001))[0]
                # require(-limit <= x <= limit and -limit <= y <= limit and buttons < (1 << 12), "Invalid saved input")
                require(-input_limit <= x <= input_limit and -input_limit <= y <= input_limit and buttons < (1 << 12),
                        "Invalid saved input")
                if maximum:
                    require((x, y, buttons) == (((index + slot) % 9 - 4) / 4,
                                               ((index * 3 + slot) % 9 - 4) / 4,
                                               (index + slot) % 2), "Maximum replay input changed")
            if index == count - 1:
                require(state_hash == final_hash, "Replay final hash differs")
        require(not stream.read(1), "Unexpected replay suffix")
    return dict(seed=seed, scenario=scenario, frames=count, slots=slots, bytes=size,
                final_hash=final_hash, sha256=sha(path))


def compare_confirmed_prefix(paths, decoded):
    """Disconnects may leave different confirmed lengths; compare EVERY shared record."""
    require(len(paths) == len(decoded) == 2, "Expected two complete saved replays")
    left, right = decoded
    require(all(left[key] == right[key] for key in ('seed', 'scenario', 'slots')), "Replay session differs")
    count = min(left['frames'], right['frames'])
    require(count > 0, "Empty confirmed prefix")
    length = 12 + left['slots'] * 10
    digest = hashlib.sha256()
    offset = 28 + len(left['scenario'].encode('utf-8'))
    with paths[0].open('rb') as first, paths[1].open('rb') as second:
        first.seek(offset); second.seek(offset)
        for frame in range(count):
            a, b = first.read(length), second.read(length)
            require(len(a) == length and a == b, f"Shared replay input/hash differs at record {frame}")
            digest.update(a)
    return dict(shared_frames=count, sha256=digest.hexdigest(),
                terminal_frames=[left['frames'], right['frames']])


def verify_actual_wire(path, decoded, directory):
    """Independently match every fixed replay input and server checkpoint to captured bytes."""
    require(decoded['frames'] == 21 and decoded['slots'] == 2, "Fixed replay shape differs")
    authority = (directory / 'authority1.bin').read_bytes()
    hashes = (directory / 'hashes1.bin').read_bytes()
    require(len(authority) == 21 * 27 and len(hashes) == 3 * 13, "Fixed wire capture incomplete")
    require(authority == (directory / 'authority2.bin').read_bytes() and
            hashes == (directory / 'hashes2.bin').read_bytes(), "Actual server streams differ")
    with path.open('rb') as replay:
        replay.seek(28 + len(decoded['scenario'].encode('utf-8')))
        for frame in range(21):
            record = replay.read(32)
            require(len(record) == 32, "Missing saved fixed frame")
            saved_frame, saved_hash = struct.unpack('<IQ', record[:12])
            packet = authority[frame * 27:(frame + 1) * 27]
            require(struct.unpack('<BIH', packet[:7]) == (3, frame, 2) and saved_frame == frame and
                    record[12:] == packet[7:], "Saved input differs from actual server input")
            if frame % 10 == 0:
                packet = hashes[frame // 10 * 13:(frame // 10 + 1) * 13]
                require(struct.unpack('<BIQ', packet) == (4, frame, saved_hash),
                        "Saved checkpoint differs from actual server hash")
    return dict(frames=21, server_checkpoints=3, authority_sha256=sha(directory / 'authority1.bin'),
                hashes_sha256=sha(directory / 'hashes1.bin'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (args.output or ROOT / f".project/optimization/benchmarks/replay-persistence-{time.time_ns()}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, ASAN_OPTIONS="halt_on_error=1:detect_leaks=1:quarantine_size_mb=16",
                       UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1", LSAN_OPTIONS="exitcode=23")
    environment.pop("LD_PRELOAD", None)
    sources = ["engine/src/frame_sync/replay_system.hpp", "engine/src/frame_sync/replay_file.hpp",
               "engine/src/frame_sync/integrated_client.cpp", "engine/tests/replay_file_test.cpp",
               "engine/tests/memory_budget_test.cpp", "engine/tests/replay_integration_test.cpp",
               "engine/tests/phase16_integration_test.cpp", "engine/tests/frame_sync_test.cpp",
               "engine/tests/engine_integration_test.cpp", "engine/tests/CMakeLists.txt", "engine/sources.cmake",
               ".project/checks/replay_persistence.py", ".project/checks/integrated_tcp_probe.py"]
    # 2026-09-13: directory admission is exercised through the real client too.
    sources += ["engine/src/frame_sync/replay_directory.hpp", "engine/tests/replay_directory_test.cpp",
                ".project/checks/native_replay_directory_probe.py", ".project/checks/fixed_frame_relay.py"]
    # 2026-09-10: pin the complete engine/resources as well as the directly exercised files.
    # original = {name: sha(ROOT / name) for name in sources}
    # 2026-09-10: the shared manifest API returns the hashes mapping directly.
    # original, _ = source_manifest()
    original = source_manifest()
    original.update({name: sha(ROOT / name) for name in sources})
    commands, cases, binaries = [], [], {}
    markers = ("ERROR: AddressSanitizer", "ERROR: LeakSanitizer", "runtime error:",
               "AddressSanitizer:DEADLYSIGNAL", "SUMMARY: UndefinedBehaviorSanitizer")

    def run(command, name, *, extra=None, timeout=600):
        command = list(map(str, command))
        log = output / (name + ".log")
        started = time.monotonic()
        with log.open("w") as stream:
            result = subprocess.run(command, cwd=ROOT, env=dict(environment, **(extra or {})),
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        record = dict(argv=command, returncode=result.returncode, log=log.name,
                      log_sha256=sha(log), seconds=time.monotonic() - started)
        commands.append(record)
        (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        text = log.read_text()
        require(result.returncode == 0 and not any(marker in text for marker in markers),
                f"Native replay contract failed; see {log}")
        return text

    # 2026-09-10: include the actual concurrent-reader publication contract.
    # targets = {"replay_file_test": 9, "memory_budget_test": 21, "replay_integration_test": 4,
    targets = {"replay_file_test": 10, "memory_budget_test": 21, "replay_integration_test": 4,
               "phase16_integration_test": 20, "frame_sync_test": 18, "engine_integration_test": 15}
    targets["replay_directory_test"] = 16
    cached_gtest = Path("/tmp/football-review-20260909-tests/_deps/googletest-src")
    require(cached_gtest.is_dir(), "Configure the documented local GoogleTest source before this native check")
    for label, tests, native, sanitize in (
            ("ordinary", Path("/tmp/football-optimization-tests"), Path("/tmp/football-optimization-native"), "OFF"),
            ("sanitized", Path("/tmp/football-optimization-query-tests"), Path("/tmp/football-optimization-sanitized"), "ON")):
        run(["cmake", "-S", "engine/tests", "-B", tests, "-DCMAKE_BUILD_TYPE=Debug", "-DENABLE_PCH=OFF",
             f"-DENABLE_ASAN={sanitize}", f"-DENABLE_UBSAN={sanitize}", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
             f"-DFETCHCONTENT_SOURCE_DIR_GOOGLETEST={cached_gtest}"], label + "-configure")
        run(["cmake", "--build", tests, "-j", "1", "--target", *targets], label + "-build-tests")
        dynamic = run(["readelf", "-d", tests / "replay_file_test"], label + "-dependencies")
        require(("libasan" in dynamic) == (sanitize == "ON") and
                ("libubsan" in dynamic) == (sanitize == "ON"), "Wrong test detector configuration")
        for target, minimum in targets.items():
            report = output / f"{label}-{target}.json"
            extra = {"FOOTBALL_REPLAY_FILE_EVIDENCE": str(output / f"{label}-maximum.bin")} if target == "replay_file_test" else {}
            # Same explicit separation as tests/CMakeLists.txt: timing cases run
            # in the Release performance stage, not these Debug/ASan contracts.
            text = run([tests / target, "--gtest_filter=-PerformanceTest.*", f"--gtest_output=json:{report}"],
                       label + "-" + target, extra=extra, timeout=180)
            result = json.loads(report.read_text())
            require(result["tests"] >= minimum and not any(result.get(k, 0) for k in ("failures", "errors", "disabled")),
                    "Missing or failing replay regression cases")
            tests_run = [case for suite in result["testsuites"] for case in suite["testsuite"]]
            require(len(tests_run) == result["tests"] and all(case["status"] == "RUN" and case["result"] == "COMPLETED"
                                                               for case in tests_run), "Skipped replay regression case")
            row = dict(label=label, target=target, tests=result["tests"], report=report.name, sha256=sha(report))
            if target == "replay_file_test":
                records = [json.loads(line.removeprefix("REPLAY_FILE_EVIDENCE "))
                           for line in text.splitlines() if line.startswith("REPLAY_FILE_EVIDENCE ")]
                require(len(records) == 1, "Missing maximum-file RSS observations")
                row["maximum_save"] = records[0]
                row["independent_decode"] = read_replay(output / f"{label}-maximum.bin", maximum=True)
            cases.append(row)
            binaries[f"{label}/{target}"] = dict(path=str(tests / target), sha256=sha(tests / target))
        run(["cmake", "--build", native, "-j", "1", "--target", "football_client_tcp", "football_server_tcp",
             "engine_memory_contract"], label + "-build-native")
        memory = run([native / "bin/engine_memory_contract"], label + "-memory",
                     extra={"LD_LIBRARY_PATH": str(native)}, timeout=180)
        summary = json.loads([line for line in memory.splitlines() if line.startswith("{")][-1])
        require(summary["passed"] and summary["assertions"] >= 1498 and summary["skipped"] == 0,
                "Incomplete actual GameEnv rollback/replay contract")
        # 2026-09-13: count explicit native scenarios as the runner grows.
        # cases.append(dict(label=label, target="native_memory", contract=summary))
        cases.append(dict(label=label, target="native_memory", native_cases=1, contract=summary))
        pair = output / (label + "-pair")
        run([sys.executable, ROOT / ".project/checks/integrated_tcp_probe.py", "--build", native,
             "--output", pair, "--pair-only"], label + "-pair", timeout=180)
        result = json.loads((pair / "report.json").read_text())
        require(result["passed"], "Actual native clients did not save their confirmed replay")
        decoded = [read_replay(pair / "two_actual_players" / f"player{number}" / "replay_42.bin") for number in (1, 2)]
        clients = result["cases"][0]["clients"]
        require(len(clients) == 2, "Missing actual client telemetry")
        require(all(row["frames"] == client["confirmed"] and row["slots"] == 2 for row, client in zip(decoded, clients)),
                "Saved frame count differs from actual client confirmations")
        # 2026-09-13: SIGTERM during a broadcast does not establish a common
        # terminal frame. Preserve the abrupt-disconnect case and require every
        # shared input/hash to agree; full-file equality is enforced separately
        # below with an explicit, real-server fixed boundary.
        # require(decoded[0] == decoded[1], "Actual clients saved different replay bytes")
        paths = [pair / "two_actual_players" / f"player{number}" / "replay_42.bin" for number in (1, 2)]
        shared = compare_confirmed_prefix(paths, decoded)
        # 2026-09-13: preserve the paired deterministic replay alongside quota cases.
        # cases.append(dict(label=label, target="native_pair", contract=result, independent_decode=decoded))
        cases.append(dict(label=label, target="native_pair", native_cases=1, contract=result,
                          independent_decode=decoded, shared_prefix=shared))
        fixed = output / (label + "-fixed-pair")
        run([sys.executable, ROOT / ".project/checks/integrated_tcp_probe.py", "--build", native,
             "--output", fixed, "--fixed-pair-only"], label + "-fixed-pair", timeout=180)
        result = json.loads((fixed / "report.json").read_text())
        require(result["passed"] and len(result["cases"]) == 1, "Fixed native pair did not complete")
        paths = [fixed / "two_actual_players" / f"player{number}" / "replay_42.bin" for number in (1, 2)]
        decoded = [read_replay(path) for path in paths]
        require(decoded[0] == decoded[1] and all(row['frames'] == 21 for row in decoded),
                "Fixed actual clients saved different or incomplete replay bytes")
        wire = verify_actual_wire(paths[0], decoded[0], fixed / "two_actual_players")
        cases.append(dict(label=label, target="native_fixed_pair", native_cases=1, contract=result,
                          independent_decode=decoded, actual_wire=wire))
        directory = output / (label + "-directory")
        run([sys.executable, ROOT / ".project/checks/native_replay_directory_probe.py", "--build", native,
             "--output", directory], label + "-directory", timeout=240)
        result = json.loads((directory / "report.json").read_text())
        require(result["passed"] and result["assertions"] == 5 and result["skipped"] == 0,
                "Missing actual native directory quota/refusal/recovery cases")
        cases.append(dict(label=label, target="native_directory", native_cases=5, contract=result))
        for name in ("bin/football_client_tcp", "bin/football_server_tcp", "bin/engine_memory_contract", "libfootball_engine.so"):
            binaries[f"{label}/{name}"] = dict(path=str(native / name), sha256=sha(native / name))
    # 2026-09-10: detect changed or newly introduced native inputs during the run.
    # require(original == {name: sha(ROOT / name) for name in sources}, "Replay sources changed during verification")
    # 2026-09-10: same mapping contract when checking end-of-run freshness.
    # current, _ = source_manifest()
    current = source_manifest()
    current.update({name: sha(ROOT / name) for name in sources})
    require(original == current, "Replay sources changed during verification")
    report = dict(passed=True, skipped=0, unit_cases=sum(row.get("tests", 0) for row in cases),
                  cases=cases, sources=original, binaries=binaries, commands=commands,
                  # 2026-09-13: aggregate native storage and killed writers are now exercised.
                  # scope="Linux native save scratch, per-file capacity, failure recovery and actual TCP client replay; "
                  #       "excludes aggregate disk quota, crash-orphan cleanup, full-process soak and GPU budgets")
                  native_cases=sum(row.get("native_cases", 0) for row in cases),
                  scope="Linux local native atomic save, per-file and cooperative directory quotas, killed-writer "
                        "recovery and actual GameEnv TCP client replay; excludes full-process soak and GPU budgets")
    destination = output / "report.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    # 2026-09-13: include all actually exercised native scenarios.
    # print(json.dumps(dict(passed=True, assertions=report["unit_cases"] + 4, skipped=0,
    print(json.dumps(dict(passed=True, assertions=report["unit_cases"] + report["native_cases"], skipped=0,
                          # 2026-09-10: explicit --output may be outside the checkout.
                          # artifact=str(destination.relative_to(ROOT)), artifact_sha256=sha(destination))))
                          artifact=str(destination), artifact_sha256=sha(destination))))


if __name__ == "__main__":
    main()
