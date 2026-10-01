#!/usr/bin/env python3
"""Build and exercise the real PPO checkpoint path, including failed restores."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def command(argv, *, env=None, timeout=900, good=True):
    result = subprocess.run([str(part) for part in argv], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=timeout)
    if good:
        require(result.returncode == 0,
                f"{argv[0]} failed ({result.returncode}): {result.stderr[-2000:]}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path,
                        default=Path("/tmp/football-rl-training-build"))
    parser.add_argument("--tests-build", type=Path,
                        default=Path("/tmp/football-optimization-tests"))
    args = parser.parse_args()
    build, tests = args.build.resolve(), args.tests_build.resolve()
    require(build != tests, "Training and test build directories must differ")
    env = dict(os.environ, GFOOTBALL_DATA_DIR=str(ROOT / "engine/data"),
               SDL_VIDEODRIVER="dummy", PYTHONOPTIMIZE="0")
    for key in ("LD_PRELOAD", "DISPLAY", "LD_LIBRARY_PATH"):
        env.pop(key, None)
    command(["cmake", "-S", "engine", "-B", build, "-DCMAKE_BUILD_TYPE=Release",
             "-DBUILD_PYTHON_BINDINGS=OFF", "-DBUILD_RL_TRAINING=ON"])
    command(["cmake", "--build", build, "-j", "2", "--target", "rl_football_training"],
            timeout=3600)
    binary = build / "rl_football_training"
    require(binary.is_file(), "Missing native training binary")
    command(["cmake", "-S", "engine/tests", "-B", tests,
             "-DCMAKE_BUILD_TYPE=Release"])
    command(["cmake", "--build", tests, "-j", "2", "--target",
             "replay_file_test", "replay_directory_test", "checkpoint_file_test"],
            timeout=1800)
    suites = command(["ctest", "--test-dir", tests, "-R",
                      r"^(CheckpointFileTest|ReplayFileTest|ReplayDirectoryTest)\.",
                      "--output-on-failure", "-j", "1"]).stdout
    match = re.search(r"100% tests passed(?:, 0 tests failed)? out of (\d+)", suites)
    require(match and int(match.group(1)) >= 38,
            "Checkpoint and replay atomic-file suites are incomplete")

    with tempfile.TemporaryDirectory(prefix="football-checkpoint-contract-") as folder:
        folder = Path(folder)
        prefix = folder / "first"
        first = command([binary, "--max-loop-steps", "1", "--save", prefix, "42"],
                        env=env, timeout=120)
        checkpoint = folder / "first_final.tar"
        require(checkpoint.is_file() and
                "Training stopped at requested limit. Steps: 1" in first.stdout,
                "Fresh one-loop training did not publish a checkpoint")
        sealed = checkpoint.read_bytes()
        require(len(sealed) > 1024 and sealed[-64:-56] == b"FBCKPT02" and
                hashlib.sha256(sealed[:-64]).digest() == sealed[-40:-8],
                "Checkpoint footer or digest is invalid")
        with tarfile.open(checkpoint) as archive:
            members = archive.getmembers()
        require(len(members) > 100, "PPO archive is missing tensor entries")
        resumed = command([binary, "--load", checkpoint, "--max-loop-steps", "1",
                           "--save", folder / "resumed", "42"], env=env, timeout=120)
        require("loaded from" in resumed.stdout and "(step=1)" in resumed.stdout and
                "Steps: 2" in resumed.stdout and
                (folder / "resumed_final.tar").is_file(),
                "Cross-process PPO restore did not advance the saved state")

        def rejected(name, payload, diagnostic):
            path = folder / name
            path.write_bytes(payload)
            result = command([binary, "--load", path, "--max-loop-steps", "1", "42"],
                             env=env, timeout=30, good=False)
            require(result.returncode == 1 and diagnostic in result.stderr and
                    "refusing to start with a new policy" in result.stderr,
                    f"{name} was not rejected safely: {result.returncode} {result.stderr}")

        rejected("truncated.tar", sealed[:-10], "checkpoint footer")
        damaged = bytearray(sealed)
        damaged[2048] ^= 1
        rejected("damaged.tar", damaged, "checkpoint SHA-256 mismatch")
        changed = bytearray(sealed)
        for member in members:
            if member.name == "meta" or member.name.endswith("/meta"):
                position = changed.find(b"dim_0:", member.offset_data,
                                        member.offset_data + member.size)
                if position >= 0:
                    changed[position + 7:position + 10] = b"999"
                    break
        else:
            raise AssertionError("PPO archive has no tensor dimension metadata")
        changed[-40:-8] = hashlib.sha256(changed[:-64]).digest()
        rejected("wrong-dimension.tar", changed, "archive tensor metadata differs")
        rejected("legacy-unsealed.tar", sealed[:-64], "checkpoint footer")
        invalid = command([binary, "--save-interval", "0", "--max-loop-steps", "1"],
                          env=env, timeout=30, good=False)
        require(invalid.returncode == 1 and
                "Save interval must be positive" in invalid.stderr,
                "Zero autosave interval did not fail before training")
        target = folder / "blocked_final.tar"
        target.mkdir()
        blocked = command([binary, "--save", folder / "blocked",
                           "--max-loop-steps", "1"], env=env, timeout=120, good=False)
        require(blocked.returncode == 1 and "Failed to save final checkpoint" in
                blocked.stderr and target.is_dir(),
                "Checkpoint writer silently accepted a non-file destination")

    # The GameEnv wrapper owns one global instance; Debug may not override this
    # safety guard or force Release optimization/fast-math.
    source = (ROOT / "engine/src/frame_sync/rl_training/training.cpp").read_text()
    require("static_assert(CONFIG::LOOP_CORE_CONFIG::CORE_PARAMETERS::N_ENVIRONMENTS == 1" in
            source and "static constexpr TI N_ENVIRONMENTS = 1" in source,
            "Single-environment guard is missing")
    debug = build.parent / (build.name + "-debug-config")
    command(["cmake", "-S", "engine", "-B", debug, "-DCMAKE_BUILD_TYPE=Debug",
             "-DBUILD_PYTHON_BINDINGS=OFF", "-DBUILD_RL_TRAINING=ON"])
    rows = json.loads((debug / "compile_commands.json").read_text())
    recipe = next((row for row in rows if row["file"].endswith("/rl_training/training.cpp")),
                  None)
    require(recipe is not None, "Debug PPO translation unit is missing")
    flags = shlex.split(recipe["command"])
    require("-g" in flags and not any(flag in flags for flag in
            ("-O2", "-O3", "-Ofast", "-ffast-math", "-DNDEBUG")),
            "Debug PPO build has Release optimization flags")
    print(json.dumps({"passed": True, "skipped": 0, "assertions": 38 + 13,
                      "atomic_file_tests": int(match.group(1)),
                      "tar_members": len(members),
                      "save_restore_steps": [1, 2],
                      "rejected": ["truncated", "damaged", "wrong-dimension",
                                   "legacy-unsealed", "invalid-interval",
                                   "non-file-destination"],
                      "single_environment": True,
                      "debug_flags": "validated",
                      "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
