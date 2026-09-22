#!/usr/bin/env python3
"""Drive the real UDP client against a bounded local fault-injecting peer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def packet(sequence, payload):
    return struct.pack("<BIH", 0, sequence, len(payload)) + payload


def probe(binary, case, environment, output):
    started = time.monotonic()
    frames = []
    ready = False
    sent_faults = 0
    pending_fault = None
    destination = None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        peer.bind(("127.0.0.1", 0))
        peer.settimeout(0.02)
        process = subprocess.Popen(
            [str(binary), "127.0.0.1", str(peer.getsockname()[1]), "--headless"],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            while process.poll() is None and time.monotonic() - started < 15:
                try:
                    data, address = peer.recvfrom(4096)
                except socket.timeout:
                    continue
                if destination is None:
                    require(data == b"\0", "Client did not send the expected Connect")
                    destination = address
                    session = struct.pack("<BIHH", 5, 42, 11, 11)
                    slots = (struct.pack("<BH", 7, 65535) if case == "invalid_slots" else
                             struct.pack("<BH", 7, 22) + struct.pack("<22H", *range(22)))
                    peer.sendto(packet(0, session), destination)
                    peer.sendto(packet(1, slots), destination)
                    continue
                require(address == destination, "Unexpected peer in isolated probe")
                if len(data) == 5 and data[0] == 255:
                    sequence = struct.unpack_from("<I", data, 1)[0]
                    if pending_fault == sequence and case == "receive_capacity" and sent_faults < 4:
                        pending_fault += 1
                        peer.sendto(packet(pending_fault, b"\x05" + bytes(1189)), destination)
                        sent_faults += 1
                    continue
                require(len(data) >= 7 and data[0] == 0, "Bad reliable client datagram")
                _, sequence, length = struct.unpack_from("<BIH", data)
                require(length == len(data) - 7, "Truncated client payload")
                if case != "no_ack":
                    peer.sendto(struct.pack("<BI", 255, sequence), destination)
                payload = data[7:]
                if payload[0] == 6:
                    ready = True
                if payload[0] == 2:
                    _, frame, count = struct.unpack_from("<BIH", payload)
                    require(count == 22 and len(payload) == 7 + 22 * 12,
                            "Full 22-slot input did not fit the actual client packet")
                    frames.append(frame)
                    if not sent_faults and case in ("invalid_authority", "receive_capacity"):
                        pending_fault = 2
                        fault = (struct.pack("<BIH", 3, 0, 65535) if case == "invalid_authority"
                                 else b"\x05" + bytes(1189))
                        peer.sendto(packet(pending_fault, fault), destination)
                        sent_faults = 1
            require(process.poll() is not None, f"{case}: real client failed to stop within 15 seconds")
            text, _ = process.communicate(timeout=2)
        finally:
            if process.poll() is None:
                process.kill()
                text, _ = process.communicate(timeout=2)
                (output / f"{case}.log").write_text(text)
        (output / f"{case}.log").write_text(text)
        require(process.returncode == 1, f"{case}: expected observable connection failure, got {process.returncode}: {text}")
        require(not any(marker in text for marker in ("AddressSanitizer", "LeakSanitizer", "runtime error:")),
                f"{case}: sanitizer failure cannot count as an expected exit: {text}")
        require("UDP connection stopped:" in text, f"{case}: missing failure reason")
        if case == "invalid_slots":
            require(not ready and not frames and "GameEnv initialized:" not in text,
                    "Invalid slot count reached engine initialization")
        else:
            require(ready and frames, f"{case}: client never reached real engine gameplay: {text}")
            require("GameEnv initialized: 11v11" in text, "Probe did not initialize the real engine")
        if case == "no_ack":
            require("retries exhausted" in text, "No-ACK case failed for the wrong reason")
        if case == "receive_capacity":
            require(sent_faults == 4, "Receive test did not fill the 4096-byte buffer")
        return {"case": case, "passed": True, "exit": process.returncode,
                "frame_inputs": len(frames), "fault_packets": sent_faults,
                "seconds": time.monotonic() - started,
                "log": str(output / f"{case}.log")}


def pair_probe(build, environment, output):
    """Forward a real match, then remove ACKs to check graceful client failure.

    The server has no signal shutdown contract yet: this test terminates its
    own server process, and makes no server-destructor/leak acceptance claim.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        server_port = reservation.getsockname()[1]
    server_log = output / "pair_server.log"
    client_log = output / "pair_client.log"
    server = client = None
    started = time.monotonic()
    frames, hashes, input_sequences = set(), set(), set()
    dropping = False
    forwarded_frames = 0
    events = []
    with server_log.open("w") as server_output, client_log.open("w") as client_output:
        try:
            server = subprocess.Popen([str(build / "bin/football_server"), str(server_port), "11", "11", "42"],
                                      env=environment, stdout=server_output, stderr=subprocess.STDOUT)
            # Wait for the real engine to finish startup and bind its UDP socket.
            while time.monotonic() - started < 30:
                require(server.poll() is None, "Native server failed during initialization")
                # 2026-09-09: /proc can briefly retain the just-closed reservation.
                # ports = [int(line.split()[1].split(":")[1], 16)
                #          for line in Path("/proc/net/udp").read_text().splitlines()[1:]]
                # if server_port in ports:
                owned_sockets = set()
                for entry in Path(f"/proc/{server.pid}/fd").iterdir():
                    try:
                        link = os.readlink(entry)
                    except FileNotFoundError:
                        continue
                    if link.startswith("socket:["):
                        owned_sockets.add(link[8:-1])
                rows = [line.split() for line in Path("/proc/net/udp").read_text().splitlines()[1:]]
                if any(int(row[1].split(":")[1], 16) == server_port and row[9] in owned_sockets for row in rows):
                    break
                time.sleep(0.02)
            else:
                raise RuntimeError("Native server did not bind within 30 seconds")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as proxy:
                proxy.bind(("127.0.0.1", 0))
                proxy.settimeout(0.02)
                remote = ("127.0.0.1", server_port)
                client_endpoint = None
                client = subprocess.Popen([str(build / "bin/football_client"), "127.0.0.1",
                                           str(proxy.getsockname()[1]), "--headless"], env=environment,
                                          stdout=client_output, stderr=subprocess.STDOUT)
                while client.poll() is None and time.monotonic() - started < 60:
                    try:
                        data, address = proxy.recvfrom(4096)
                    except socket.timeout:
                        continue
                    if address == remote:
                        if len(events) < 64:
                            events.append({"direction": "server", "bytes": len(data), "prefix": data[:16].hex()})
                        require(client_endpoint is not None, "Server sent before client connected")
                        if len(data) >= 8 and data[0] == 0:
                            payload = data[7:]
                            if payload[0] == 3:
                                _, frame, count = struct.unpack_from("<BIH", payload)
                                require(count == 22 and len(payload) == 227, "Malformed real authority")
                                frames.add(frame)
                            elif payload[0] == 4:
                                hashes.add(struct.unpack_from("<I", payload, 1)[0])
                        if len(frames) >= 12:
                            dropping = True
                        if not dropping:
                            proxy.sendto(data, client_endpoint)
                            forwarded_frames = len(frames)
                    else:
                        if len(events) < 64:
                            events.append({"direction": "client", "bytes": len(data), "prefix": data[:16].hex()})
                        if client_endpoint is None:
                            client_endpoint = address
                        require(address == client_endpoint, "Unexpected client in isolated proxy")
                        if len(data) >= 8 and data[0] == 0 and data[7] == 2:
                            input_sequences.add(struct.unpack_from("<I", data, 1)[0])
                        proxy.sendto(data, remote)
                require(client.poll() is not None, "Client did not exit after deliberate delivery failure")
        finally:
            (output / "pair_packets.json").write_text(json.dumps(events, indent=2) + "\n")
            for child in (client, server):
                if child is not None and child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
    text = client_log.read_text()
    require(dropping and forwarded_frames >= 11 and hashes and len(input_sequences) >= 11,
            "Normal native pair did not advance before fault injection")
    require(client.returncode == 1 and "retries exhausted" in text, "Real pair failed for the wrong reason: " + text)
    require(not any(marker in text for marker in ("AddressSanitizer", "LeakSanitizer", "runtime error:")),
            "Sanitizer failure cannot count as an expected client exit: " + text)
    require("State hash mismatch" not in text, "Normal native pair diverged")
    require("ERROR: AddressSanitizer" not in server_log.read_text() and
            "runtime error:" not in server_log.read_text(), "Sanitizer error in native server")
    return {"passed": True, "case": "native_pair_then_no_ack", "forwarded_authority_frames": forwarded_frames,
            "observed_hash_frames": sorted(hashes), "client_input_sequences": len(input_sequences),
            "seconds": time.monotonic() - started, "client_exit": client.returncode,
            "server_shutdown": "probe termination; destructor/leak acceptance excluded"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pair-only", action="store_true")
    args = parser.parse_args()
    build = args.build.resolve()
    binary = build / "bin/football_client"
    args.output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, LD_LIBRARY_PATH=str(build), LIBGL_ALWAYS_SOFTWARE="1",
                       ASAN_OPTIONS="halt_on_error=1:detect_leaks=1:quarantine_size_mb=16",
                       UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1", LSAN_OPTIONS="exitcode=23")
    for key in ("DISPLAY", "GFOOTBALL_DATA_DIR", "GFOOTBALL_FONT", "LD_PRELOAD", "SDL_VIDEODRIVER"):
        environment.pop(key, None)
    results = []
    if args.pair_only:
        results.append(pair_probe(build, environment, args.output))
    # 2026-09-09: run the native pair separately from the already-verified peer faults.
    # for case in ("invalid_slots", "no_ack", "invalid_authority", "receive_capacity"):
    for case in (() if args.pair_only else ("invalid_slots", "no_ack", "invalid_authority", "receive_capacity")):
        result = probe(binary, case, environment, args.output)
        results.append(result)
        print(json.dumps(result), flush=True)
    report = {"passed": True, "cases": results, "skipped": 0,
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "server_sha256": hashlib.sha256((build / "bin/football_server").read_bytes()).hexdigest(),
              "engine_sha256": hashlib.sha256((build / "libfootball_engine.so").read_bytes()).hexdigest()}
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
