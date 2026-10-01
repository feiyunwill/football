"""Measure repeated XTEST input through the actual standalone product window.

This is a diagnostic, not the feel acceptance gate. It records input admission,
controlled-player velocity response, and the first subsequent product swap.
"""

import argparse
import hashlib
import json
import math
import os
import select
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CHECKS = ROOT / ".project/checks"
sys.path.insert(0, str(CHECKS))
from native_input_window_cases import Keyboard, events, require  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


def analyze(output, actions, require_causal=False):
    trace = output / "trace"
    rows = events(trace)
    steps = [row for row in rows if row["kind"] == "step"]
    timing = {row["index"]: row for row in rows if row["kind"] == "step_timing"}
    rendering = [row for row in rows if row["kind"] == "render_timing"]
    swaps = [row for row in rows if row["kind"] == "swap" and row["render_owner"]]
    human_commands = [row for row in rows if row["kind"] == "human_command"]
    animation_choices = [row for row in rows if row["kind"] == "anim_select"]
    ball_touches = [row for row in rows if row["kind"] == "ball_touch"]
    require(len(timing) == len(steps) and swaps, "Missing actual player steps or product swaps")
    samples = []
    for action in actions:
        start, end, direction = action["start_ns"], action["end_ns"], action["direction"]
        before = [row for row in steps if row["time"] < start]
        active = [row for row in steps if start <= row["time"] < end]
        require(before, f"Missing pre-press player state for press {action['index']}")
        baseline = before[-1]
        if not active:
            blocked_ms = sum(max(0, min(row["end"], end) -
                                 max(row["start"], start)) for row in rendering) / 1e6
            samples.append({"index": action["index"], "direction": direction,
                            "status": "no_simulation_step_during_press",
                            "owned_player": baseline["owned"],
                            "render_blocking_during_press_ms": round(blocked_ms, 3),
                            "input_admission_ms": None,
                            "velocity_response_ms": None})
            continue
        if baseline["owned"] < 0:
            samples.append({"index": action["index"], "direction": direction,
                            "status": "no_controlled_player_at_press"})
            continue
        require(baseline["index"] in timing, "Missing pre-press velocity")
        if not timing[baseline["index"]]["in_play"]:
            samples.append({"index": action["index"], "direction": direction,
                            "status": "match_not_in_play_at_press"})
            continue
        if timing[baseline["index"]].get("game_mode") != 0:
            samples.append({"index": action["index"], "direction": direction,
                            "status": "set_piece_at_press",
                            "game_mode": timing[baseline["index"]].get("game_mode")})
            continue
        initial_vx = timing[baseline["index"]]["vx"]
        admitted = next((row for row in active if row["x"] == direction and
                         row["owned"] == baseline["owned"] and
                         timing[row["index"]].get("game_mode") == 0), None)
        if admitted is None:
            samples.append({"index": action["index"], "direction": direction,
                            "status": "no_admitted_step_for_same_player"})
            continue
        raw_response = next((row for row in active if row["index"] >= admitted["index"] and
                          row["owned"] == baseline["owned"] and
                          timing[row["index"]]["in_play"] and
                          timing[row["index"]].get("game_mode") == 0 and
                          direction * (timing[row["index"]]["vx"] - initial_vx) >= .1), None)
        aligned_commands = [row for row in human_commands
                            if start <= row["time"] < end and
                            row.get("team_id") == 0 and
                            row.get("team_index") == baseline["owned"] and
                            row.get("hid_x") == direction and
                            row.get("desired_x", 0) * direction > .1 and
                            row.get("desired_speed", 0) > 0]
        accepted_movement = next((choice for choice in animation_choices
                                  if start <= choice["time"] < end and
                                  choice["command_type"] == 1 and
                                  choice["accepted"] is True and
                                  choice.get("desired_x", 0) * direction > .1 and
                                  any(command["player"] == choice["player"] and
                                      command["time"] <= choice["time"]
                                      for command in aligned_commands)), None)
        # A newly selected BallControl/Trap animation can also move the player.
        # Count it only when the same player later makes intentional contact;
        # an old pending touch or an uncommitted animation is not input causality.
        accepted_touch = next((choice for choice in animation_choices
                               if start <= choice["time"] < end and
                               choice["command_type"] in (2, 3) and
                               choice["accepted"] is True and
                               choice.get("desired_x", 0) * direction > .1 and
                               any(command["player"] == choice["player"] and
                                   command["time"] <= choice["time"]
                                   for command in aligned_commands) and
                               any(touch.get("player") == choice["player"] and
                                   touch.get("touch_type") == 0 and
                                   choice["time"] <= touch["time"] <= end + 100_000_000
                                   for touch in ball_touches)), None)
        accepted_action = min((choice for choice in (accepted_movement, accepted_touch)
                               if choice is not None),
                              key=lambda choice: choice["time"], default=None)
        causal_start = accepted_action["time"] if accepted_action else None
        pre_selection = next((row for row in reversed(steps)
                              if causal_start is not None and row["time"] < causal_start and
                              row["owned"] == baseline["owned"]), baseline)
        pre_selection_vx = timing[pre_selection["index"]]["vx"]
        responded = raw_response
        if require_causal:
            responded = (next((row for row in active
                               if row["index"] >= admitted["index"] and
                               row["owned"] == baseline["owned"] and
                               row["time"] >= causal_start and
                               timing[row["index"]]["in_play"] and
                               timing[row["index"]].get("game_mode") == 0 and
                               direction * (timing[row["index"]]["vx"] - initial_vx) >= .1 and
                               direction * (timing[row["index"]]["vx"] - pre_selection_vx) >= .1), None)
                         if causal_start is not None else None)
        following_admission = next((row for row in swaps if row["time"] >= admitted["time"]), None)
        following_response = (next((row for row in swaps if row["time"] >= responded["time"]), None)
                              if responded else None)
        require(following_admission is not None and (not responded or following_response),
                "No product swap after player step")
        render_blocking_ms = sum(max(0, min(row["end"], admitted["time"]) -
                                     max(row["start"], start)) for row in rendering) / 1e6
        samples.append({"index": action["index"], "direction": direction,
                        "status": "admitted" if responded else "no_velocity_response",
                        "owned_player": baseline["owned"],
                        "input_admission_ms": round((admitted["time"] - start) / 1e6, 3),
                        "render_blocking_before_admission_ms": round(render_blocking_ms, 3),
                        "raw_velocity_change_ms": (round((raw_response["time"] - start) / 1e6, 3)
                                                   if raw_response else None),
                        "first_aligned_command_ms": (round((aligned_commands[0]["time"] - start) / 1e6, 3)
                                                     if aligned_commands else None),
                        "first_accepted_aligned_movement_ms": (round((accepted_movement["time"] - start) / 1e6, 3)
                                                               if accepted_movement else None),
                        "first_accepted_aligned_touch_ms": (round((accepted_touch["time"] - start) / 1e6, 3)
                                                            if accepted_touch else None),
                        "first_accepted_aligned_action_ms": (round((causal_start - start) / 1e6, 3)
                                                             if causal_start is not None else None),
                        "causal_action_type": (accepted_action["command_type"]
                                               if accepted_action else None),
                        "pre_selection_vx": pre_selection_vx if causal_start is not None else None,
                        "velocity_response_ms": (round((responded["time"] - start) / 1e6, 3)
                                                 if responded else None),
                        "first_swap_after_admission_ms": round((following_admission["time"] - start) / 1e6, 3),
                        "first_swap_after_response_ms": (round((following_response["time"] - start) / 1e6, 3)
                                                         if following_response else None),
                        "baseline_vx": initial_vx,
                        "response_vx": timing[responded["index"]]["vx"] if responded else None,
                        "baseline_x": baseline["player_x"],
                        "response_x": responded["player_x"] if responded else None,
                        "admitted_step": admitted["index"],
                        "response_step": responded["index"] if responded else None,
                        "admission_swap_index": following_admission["index"],
                        "response_swap_index": following_response["index"] if following_response else None})
    admitted_samples = [row for row in samples if row.get("input_admission_ms") is not None]
    responses = [row["velocity_response_ms"] for row in samples
                 if row.get("velocity_response_ms") is not None]
    return {"samples": samples, "step_count": len(steps), "swap_count": len(swaps),
            "causal_trace_required": require_causal,
            "render_count": len(rendering),
            "admitted_count": len(admitted_samples),
            "response_count": len(responses),
            "render_blocked_admissions": sum(row["render_blocking_before_admission_ms"] > 0
                                             for row in admitted_samples),
            "render_blocking_p95_ms": (percentile([row["render_blocking_before_admission_ms"]
                                                  for row in admitted_samples], .95)
                                       if len(admitted_samples) >= 20 else None),
            "input_admission_p95_ms": (percentile([row["input_admission_ms"] for row in admitted_samples], .95)
                                       if len(admitted_samples) >= 20 else None),
            "observed_admission_p95_ms": (percentile([row["input_admission_ms"] for row in admitted_samples], .95)
                                           if admitted_samples else None),
            "velocity_response_p95_ms": percentile(responses, .95) if len(responses) >= 20 else None,
            "observed_response_p95_ms": percentile(responses, .95) if responses else None,
            "swap_after_admission_p95_ms": (percentile([row["first_swap_after_admission_ms"] for row in admitted_samples], .95)
                            if len(admitted_samples) >= 20 else None),
            "swap_after_response_p95_ms": (percentile([row["first_swap_after_response_ms"] for row in samples
                                                       if row.get("first_swap_after_response_ms") is not None], .95)
                                            if len(responses) >= 20 else None)}


def product(output, build, library, cycles, gpu_driver_root, seed, trace_commands):
    trace = output / "trace"
    trace.mkdir()
    tools = Path(os.environ["FOOTBALL_TEST_X11_ROOT"])
    runtime = dict(os.environ, LD_LIBRARY_PATH=str(build) + ":" + str(tools / "usr/lib"),
                   LD_PRELOAD=str(library), FOOTBALL_NATIVE_TRACE=str(trace),
                   GFOOTBALL_DATA_DIR=str(ROOT / "engine/data"))
    for key in ("LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "MESA_LOADER_DRIVER_OVERRIDE",
                "LIBGL_DRIVERS_PATH", "FOOTBALL_FEEL_COMMAND_TRACE"):
        runtime.pop(key, None)
    if trace_commands:
        runtime["FOOTBALL_FEEL_COMMAND_TRACE"] = "1"
    driver = None
    if gpu_driver_root:
        driver_lib = gpu_driver_root / "lib"
        driver = driver_lib / "libgallium-26.2.2.so"
        require(driver.is_file() and (driver_lib / "dri/d3d12_dri.so").exists(),
                "Private D3D12 driver is incomplete")
        runtime.update(LD_LIBRARY_PATH=str(build) + ":" + str(driver_lib) + ":" +
                       str(tools / "usr/lib"), LIBGL_DRIVERS_PATH=str(driver_lib / "dri"),
                       GALLIUM_DRIVER="d3d12", MESA_LOADER_DRIVER_OVERRIDE="d3d12")
    else:
        runtime["LIBGL_ALWAYS_SOFTWARE"] = "1"
    log = (output / "product.log").open("w")
    client = None
    keyboard = None
    actions = []
    try:
        client = subprocess.Popen([str(build / "bin/standalone_game"), "--seed", str(seed)],
                                  cwd=output, env=runtime, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 60
        while True:
            rows = events(trace)
            ready = next((row for row in rows if row["kind"] == "swap" and
                          row["xid"] and row["render_owner"]), None)
            playing = any(row["kind"] == "step_timing" and row["in_play"] and
                          row["sim_step"] >= 40 for row in rows)
            if ready and playing:
                break
            require(client.poll() is None and time.monotonic() < deadline,
                    "Actual match did not start with a product display")
            time.sleep(.02)
        keyboard = Keyboard()
        keyboard.focus(ready["xid"])
        mappings = Path(f"/proc/{client.pid}/maps").read_text()
        engine_binary = build / "libfootball_engine.so"
        mapped_engine = str(engine_binary.resolve()) in mappings
        require(mapped_engine, "Actual product did not load the measured engine core")
        mapped_driver = str(driver.resolve()) in mappings if driver else False
        require(not driver or mapped_driver, "Actual product did not load the requested GPU driver")
        time.sleep(.25)
        for index in range(cycles):
            require(client.poll() is None, "Actual product exited during input samples")
            observed = events(trace)
            prior_step = next((row for row in reversed(observed) if row["kind"] == "step"), None)
            prior_timing = (next((row for row in reversed(observed)
                                  if row["kind"] == "step_timing" and
                                  prior_step and row["index"] == prior_step["index"]), None))
            require(prior_step and prior_timing, "Missing current player motion before XTEST")
            prior_vx = prior_timing["vx"]
            direction = (-1 if prior_vx > .2 else 1 if prior_vx < -.2
                         else 1 if index % 2 == 0 else -1)
            key = "d" if direction > 0 else "a"
            start = time.monotonic_ns()
            keyboard.key(key, True)
            time.sleep(.34)
            end = time.monotonic_ns()
            keyboard.key(key, False)
            actions.append({"index": index, "direction": direction,
                            "selection_vx": prior_vx,
                            "selection_game_mode": prior_timing.get("game_mode"),
                            "selection_owned_player": prior_step["owned"],
                            "start_ns": start, "end_ns": end})
            time.sleep(.34)
        keyboard.tap("q")
        require(client.wait(timeout=15) == 0, "Actual product exit failed")
        (output / "actions.json").write_text(json.dumps(actions, indent=2) + "\n")
        result = analyze(output, actions, require_causal=trace_commands)
        result.update(actual_product_main=True, actual_xtest=True,
                      actual_player_velocity=True, passed=True,
                      source_sha256=sha(__file__), trace_sha256=sha(trace / "events.jsonl"),
                      actions_sha256=sha(output / "actions.json"),
                      keyboard_source_sha256=sha(CHECKS / "native_input_window_cases.py"),
                      trace_source_sha256=sha(ROOT / "engine/tests/engine_native_window_trace.cpp"),
                      product_sha256=sha(build / "bin/standalone_game"),
                      engine_core_sha256=sha(engine_binary),
                      product_mapped_engine_core=mapped_engine,
                      trace_library_sha256=sha(library), cycles=cycles,
                      seed=seed,
                      command_trace_enabled=trace_commands,
                      render_backend="private_d3d12" if driver else "llvmpipe",
                      driver_sha256=sha(driver) if driver else None,
                      product_mapped_private_driver=mapped_driver,
                      acceptance_passed=(result["response_count"] == cycles and
                                         result["admitted_count"] == result["response_count"] and
                                         result["velocity_response_p95_ms"] is not None and
                                         result["velocity_response_p95_ms"] <= 50))
        (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({key: value for key, value in result.items() if key != "samples"}),
              flush=True)
    finally:
        if keyboard:
            keyboard.close()
        if client and client.poll() is None:
            client.terminate()
            try:
                client.wait(timeout=5)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait(timeout=5)
        log.close()


def private_x11(output, build, library, cycles, parent_namespace, gpu_driver_root, seed,
                trace_commands):
    require(os.readlink("/proc/self/ns/mnt") != parent_namespace,
            "A private mount namespace is required")
    tools = Path(os.environ["FOOTBALL_TEST_X11_ROOT"])
    require(all((tools / name).is_file() for name in ("usr/bin/Xvfb", "usr/bin/xkbcomp")),
            "Relocated X11 tools are incomplete")
    if not Path("/usr/bin/xkbcomp").exists():
        overlay = Path(tempfile.mkdtemp(prefix="feel-x11-namespace-", dir=tools.parent))
        for name in ("host-bin", "upper", "work"):
            (overlay / name).mkdir()
        subprocess.run(["mount", "--bind", "/usr/bin", str(overlay / "host-bin")], check=True)
        subprocess.run(["mount", "-t", "overlay", "overlay", "-o",
                        f"lowerdir={overlay / 'host-bin'},upperdir={overlay / 'upper'},"
                        f"workdir={overlay / 'work'}", "/usr/bin"], check=True)
        Path("/usr/bin/xkbcomp").symlink_to(tools / "usr/bin/xkbcomp")
    subprocess.run(["mount", "-t", "tmpfs", "-o", "size=1m,mode=1777,nosuid,nodev",
                    "none", "/tmp/.X11-unix"], check=True)
    def field(value):
        return struct.pack("!H", len(value)) + value
    authority = output / "authority"
    authority.write_bytes(struct.pack("!H", 65535) + field(b"") + field(b"") +
                          field(b"MIT-MAGIC-COOKIE-1") + field(os.urandom(16)))
    authority.chmod(0o600)
    env = dict(os.environ, LD_LIBRARY_PATH=str(tools / "usr/lib"),
               XAUTHORITY=str(authority), SDL_VIDEODRIVER="x11", SDL_AUDIODRIVER="dummy")
    env.pop("LD_PRELOAD", None)
    read_fd, write_fd = os.pipe()
    server = None
    try:
        argv = [str(tools / "usr/bin/Xvfb"), "-displayfd", str(write_fd),
                "-screen", "0", "1280x720x24", "-nolisten", "tcp",
                "-auth", str(authority), "-xkbdir", str(tools / "usr/share/X11/xkb")]
        with (output / "xserver.log").open("w") as log:
            server = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT,
                                      pass_fds=(write_fd,))
            os.close(write_fd)
            write_fd = -1
            ready, _, _ = select.select([read_fd], [], [], 10)
            reply = os.read(read_fd, 80) if ready else b""
            require(reply.strip().isdigit() and server.poll() is None, "Xvfb startup failed")
            env["DISPLAY"] = ":" + reply.strip().decode()
            os.environ.update(env)
            product(output, build, library, cycles, gpu_driver_root, seed, trace_commands)
    finally:
        os.close(read_fd)
        if write_fd != -1:
            os.close(write_fd)
        if server:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--gpu-driver-root", type=Path)
    parser.add_argument("--trace-commands", action="store_true")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--parent-namespace")
    args = parser.parse_args()
    require(4 <= args.cycles <= 100 and 0 <= args.seed < 2**32,
            "Sample count or seed is outside the bounded diagnostic range")
    output = (args.output or ROOT / ".project/optimization/benchmarks" /
              f"feel-latency-{time.time_ns()}").resolve()
    build = args.build.resolve()
    library = build / "input-tests/libengine_native_window_trace.so"
    require(build.is_dir() and library.is_file(), "Current native input build is missing")
    if args.child:
        private_x11(output, build, library, args.cycles, args.parent_namespace,
                    args.gpu_driver_root.resolve() if args.gpu_driver_root else None,
                    args.seed, args.trace_commands)
        return
    require(output.is_relative_to(ROOT / ".project/optimization/benchmarks") and
            not output.exists(), "Use a fresh workspace evidence directory")
    output.mkdir(parents=True)
    environment = dict(os.environ)
    environment["FOOTBALL_TEST_X11_ROOT"] = str(Path(environment.get(
        "FOOTBALL_TEST_X11_ROOT", Path.home() /
        ".cache/football-input-x11-20260913-a/root-relocated")).resolve())
    environment["LD_LIBRARY_PATH"] = str(Path(environment["FOOTBALL_TEST_X11_ROOT"]) / "usr/lib")
    namespace = os.readlink("/proc/self/ns/mnt")
    argv = ["unshare", "--mount", "--propagation", "private", sys.executable,
            __file__, "--child", "--parent-namespace", namespace,
            "--build", str(build), "--output", str(output), "--cycles", str(args.cycles),
            "--seed", str(args.seed)]
    if args.gpu_driver_root:
        argv += ["--gpu-driver-root", str(args.gpu_driver_root.resolve())]
    if args.trace_commands:
        argv.append("--trace-commands")
    with (output / "probe.log").open("w") as log:
        done = subprocess.run(argv, env=environment, stdout=log,
                              stderr=subprocess.STDOUT, timeout=180)
    require(done.returncode == 0, f"Product feel probe failed: {output / 'probe.log'}")
    result = json.loads((output / "report.json").read_text())
    print(json.dumps({"passed": result["passed"],
                      "acceptance_passed": result["acceptance_passed"],
                      "cycles": result["cycles"],
                      "seed": result["seed"],
                      "render_backend": result["render_backend"],
                      "product_mapped_private_driver": result["product_mapped_private_driver"],
                      "input_admission_p95_ms": result["input_admission_p95_ms"],
                      "render_blocked_admissions": result["render_blocked_admissions"],
                      "render_blocking_p95_ms": result["render_blocking_p95_ms"],
                      "velocity_response_p95_ms": result["velocity_response_p95_ms"],
                      "swap_after_admission_p95_ms": result["swap_after_admission_p95_ms"],
                      "swap_after_response_p95_ms": result["swap_after_response_p95_ms"],
                      "artifact": str(output / "report.json"),
                      "artifact_sha256": sha(output / "report.json")}), flush=True)


if __name__ == "__main__":
    main()
