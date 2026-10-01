#!/usr/bin/env python3
"""2026-09-13: actual native client's default replay directory quota and recovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time

from integrated_tcp_probe import ROOT, clean, environment, exact, telemetry
from match_benchmark import source_manifest
from native_boundary import require
from replay_persistence import read_replay

TEMPORARY = ".football-replay-tmp-v1"
BYTE_LIMIT = 256 * 1024 * 1024


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(65536):
            digest.update(block)
    return digest.hexdigest()


def identity(path):
    status = path.stat()
    return dict(bytes=status.st_size, blocks=status.st_blocks, sha256=sha(path))


def native_session(build, working, log, env):
    """Run the current two-client product session through a real server."""
    details = dict(passed=False)
    partner = log.parent / (log.stem + "-partner")
    partner.mkdir()
    server_log = log.with_name(log.stem + "-server.log")
    partner_log = log.with_name(log.stem + "-partner.log")
    processes = []
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    with log.open("w") as stream, server_log.open("w") as server_stream, partner_log.open("w") as partner_stream:
        try:
            server = subprocess.Popen([str(build / "bin/football_server_tcp"), str(port), "1", "1", "42"],
                                      cwd=ROOT, env=env, stdout=server_stream, stderr=subprocess.STDOUT)
            processes.append(server)
            deadline = time.monotonic() + 30
            while "Integrated TCP server listening on port" not in server_log.read_text():
                require(server.poll() is None and time.monotonic() < deadline, "Product server did not start")
                time.sleep(.02)
            argv = [str(build / "bin/football_client_tcp"), "127.0.0.1", str(port),
                    "1", "1", "42", "--headless", "--frames", "21"]
            details["argv"] = argv
            target = subprocess.Popen(argv, cwd=working, env=env, stdout=stream, stderr=subprocess.STDOUT)
            peer = subprocess.Popen(argv, cwd=partner, env=env, stdout=partner_stream, stderr=subprocess.STDOUT)
            processes.extend((target, peer))
            deadline = time.monotonic() + 60
            while target.poll() is None or peer.poll() is None:
                require(server.poll() is None and time.monotonic() < deadline,
                        "Actual product clients failed to complete 21 frames")
                time.sleep(.02)
            server.terminate()
            details["exit_code"] = target.wait(timeout=5)
            require(peer.wait(timeout=5) == 0 and server.wait(timeout=5) == 0,
                    "Partner or server did not complete normally")
            text = log.read_text()
            details.update(telemetry=telemetry(text), sanitizers_clean=clean(text),
                           saved="Replay saved: replay_42.bin" in text,
                           save_failed="Replay save failed: replay_42.bin" in text)
            require(details["exit_code"] == (0 if details["saved"] else 1) and clean(text),
                    "Wrong client exit/detector result")
            # Hash publications are asynchronous; a valid 21-frame session can
            # observe two or three checkpoints before the client exits.
            require(details["telemetry"].get("confirmed", 0) >= 21 and
                    details["telemetry"].get("verified_hashes", 0) >= 2,
                    "Client saved no actual confirmed authority")
            require(details["saved"] != details["save_failed"], "Missing/unreliable save outcome")
            require((working / TEMPORARY).is_dir(), "Managed storage path was not exercised")
            details["pending"] = sorted(path.name for path in (working / TEMPORARY).glob(".football-replay-*.tmp"))
            require(not details["pending"], "Interrupted native scratch remains after save")
            if details["saved"]:
                details["decoded"] = read_replay(working / "replay_42.bin")
                require(details["decoded"]["frames"] == details["telemetry"]["confirmed"],
                        "Replay is not the actual confirmed prefix")
            details["passed"] = True
        except Exception as error:
            details["error"] = str(error)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=5)
                    details.update(forced_cleanup=True, passed=False)
    details["log"] = str(log)
    details["log_sha256"] = sha(log)
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build, output = args.build.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = source_manifest()
    extra = [".project/checks/native_replay_directory_probe.py",
             ".project/checks/replay_persistence.py", ".project/checks/integrated_tcp_probe.py"]
    sources.update({path: sha(ROOT / path) for path in extra})
    binaries = {name: sha(build / name) for name in
                ("bin/football_client_tcp", "bin/football_server_tcp", "libfootball_engine.so")}
    env = environment(build)
    cases = []

    def session(name, working, expected_save, preserved, stage=None):
        row = native_session(build, working, output / (name + ".log"), env)
        row["case"] = name
        try:
            require(row["passed"] and row["saved"] == expected_save, "Unexpected native save outcome")
            row["preserved"] = {str(path.relative_to(output)): identity(path) for path in preserved}
            require(row["preserved"] == {str(path.relative_to(output)): value for path, value in preserved.items()},
                    "Existing storage changed on quota refusal/recovery")
            if stage:
                require(f"stage={stage}, committed=0" in Path(row["log"]).read_text(),
                        "Client did not report the expected pre-publication refusal")
        except Exception as error:
            row.update(passed=False, error=str(error))
        cases.append(row)
        print(json.dumps(row), flush=True)

    count = output / "count"; count.mkdir()
    preserved = {}
    for seed in range(1000, 1064):
        path = count / f"replay_{seed}.bin"
        path.write_bytes(f"preserved fixture {seed}".encode())
        preserved[path] = identity(path)
    session("count_refused", count, False, preserved, "admit replay file count")
    require(not (count / "replay_42.bin").exists(), "Quota refusal published an extra file")
    released = count / "replay_1000.bin"
    released.unlink()  # Exact fixture created above, inside this newly owned evidence directory.
    del preserved[released]
    session("count_recovered", count, True, preserved)

    byte = output / "bytes"; byte.mkdir()
    old = byte / "replay_42.bin"; old.write_bytes(b"previous published replay")
    occupied = byte / "replay_9000.bin"
    with occupied.open("xb") as stream:
        stream.truncate(BYTE_LIMIT - old.stat().st_size)
    preserved = {path: identity(path) for path in (old, occupied)}
    session("bytes_refused", byte, False, preserved, "admit replay bytes")
    occupied.unlink()  # Release only this probe's exact sparse quota fixture.
    session("bytes_recovered", byte, True, {})

    recovery = output / "recovery"; recovery.mkdir()
    temporary = recovery / TEMPORARY; temporary.mkdir(mode=0o700)
    orphan = temporary / ".football-replay-123-456.tmp"
    with orphan.open("xb") as stream:
        stream.write(b"interrupted application scratch")
    orphan.chmod(0o600)
    keep = temporary / "keep.txt"; keep.write_bytes(b"user-owned unrelated entry")
    session("owned_scratch_recovered", recovery, True, {keep: identity(keep)})

    current = source_manifest()
    current.update({path: sha(ROOT / path) for path in extra})
    require(sources == current, "Native replay directory sources changed during check")
    require(binaries == {name: sha(build / name) for name in binaries}, "Native binaries changed during check")
    report = dict(passed=len(cases) == 5 and all(row["passed"] for row in cases), skipped=0,
                  assertions=len(cases), cases=cases, sources=sources, binaries=binaries,
                  scope="actual GameEnv TCP client default count/byte admission, independent replay decoding, "
                        "refusal preserves existing files, explicit capacity release and owned scratch recovery; "
                        "peer is a bounded protocol fixture; true killed-writer locking is covered by native unit tests")
    destination = output / "report.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(passed=report["passed"], assertions=report["assertions"], skipped=0,
                          artifact=str(destination), artifact_sha256=sha(destination))))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
