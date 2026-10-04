#!/usr/bin/env python3
"""Freeze the player-switch bot-selection replay without rewriting prior oracles."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / ".project/optimization/baselines"
FIXTURES = ROOT / "engine/tests/fixtures"
SOURCE = ROOT / "engine/tests/engine_native_bot_selection_contract.cpp"
NAME = "bot_selection_player_switch_20261004"
HEADER = b"// Current player switch bot replay oracle, generated twice on 2026-10-04.\n"
SOURCES = (
    "engine/src/onthepitch/player/controller/humancontroller.cpp",
    "engine/src/onthepitch/player/controller/humancontroller.hpp",
    "engine/src/onthepitch/player/controller/playercontroller.cpp",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fields(line: str) -> list[str]:
    return line.strip().rstrip(",").strip("{}").split(",")


def packed(entries: dict[str, bytes]) -> bytes:
    members = {
        "manifest.json": (
            json.dumps({"format": "bot-selection-player-switch-oracle-v1",
                        "files": {name: digest(data) for name, data in sorted(entries.items())}},
                       sort_keys=True, indent=2).encode() + b"\n"
        ),
        **entries,
    }
    stream = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, data in sorted(members.items()):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def main() -> None:
    build = Path("/tmp/football-optimization-native").resolve()
    executable = build / "bin/engine_native_bot_selection_contract"
    for path in (executable, build / "libfootball_engine.so", SOURCE):
        if not path.is_file():
            raise RuntimeError(f"Missing replay input: {path}")
    for target in (BASE / f"{NAME}.json", BASE / f"{NAME}.tar.gz"):
        if target.exists():
            raise RuntimeError(f"Versioned replay already exists: {target}")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "engine/src"],
                      cwd=ROOT).returncode:
        raise RuntimeError("Current gameplay source differs from the pinned commit")
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                            text=True).strip()
    environment = dict(os.environ, LD_LIBRARY_PATH=str(build),
                       GFOOTBALL_DATA_DIR=str(ROOT / "engine/data"),
                       LIBGL_ALWAYS_SOFTWARE="1")
    environment.pop("LD_PRELOAD", None)
    members = {"generator.cpp": SOURCE.read_bytes()}
    with tempfile.TemporaryDirectory(prefix="football-bot-player-switch-oracle-") as directory:
        temporary = Path(directory)
        for run in (1, 2):
            hashes = temporary / f"hashes-run{run}.inc"
            tail = temporary / f"tail-run{run}.inc"
            for label, args in (("run", ["--emit-reference", str(hashes), str(tail)]),
                                ("normal-run", [])):
                result = subprocess.run([str(executable), *args], cwd=ROOT,
                                        env=environment, capture_output=True, timeout=120)
                log = f"exit={result.returncode}\n".encode() + result.stdout + result.stderr
                members[f"{label}{run}.log"] = log
                if result.returncode:
                    raise RuntimeError(log.decode(errors="replace"))
            members[f"hashes-run{run}.inc"] = hashes.read_bytes()
            members[f"tail-run{run}.inc"] = tail.read_bytes()
    for name, first, second in (
        ("hashes", "hashes-run1.inc", "hashes-run2.inc"),
        ("tail", "tail-run1.inc", "tail-run2.inc"),
        ("emitted report", "run1.log", "run2.log"),
        ("normal report", "normal-run1.log", "normal-run2.log"),
    ):
        if members[first] != members[second]:
            raise RuntimeError(f"Independent {name} replays differ")
    emitted = json.loads(members["run1.log"].decode().split("\n", 1)[1])
    normal = json.loads(members["normal-run1.log"].decode().split("\n", 1)[1])
    if emitted != {"passed": True, "assertions": 4921, "prefix_frames": 512,
                   "recorded_tail_frames": 2151, "unavailable_frames": 30,
                   "skipped": 0, "actual_gameenv": True, "recovered_frames": 66,
                   "opponent_restart_wait_frames": 0}:
        raise RuntimeError(f"Unexpected emitted replay: {emitted}")
    if normal != {**emitted, "assertions": 11610}:
        raise RuntimeError(f"Unexpected normal replay: {normal}")
    previous = BASE / "bot_selection_ai_mirror_20261004.json"
    prior = json.loads(previous.read_text())
    if prior["id"] != "bot-selection-ai-mirror-20261004":
        raise RuntimeError("Wrong historical replay")
    old_hashes = (FIXTURES / "native_bot_transition_hashes_ai_mirror_20261004.inc").read_text().splitlines()[1:]
    hashes = members["hashes-run1.inc"].decode().splitlines()
    changed = [index for index, (old, new) in enumerate(zip(old_hashes, hashes))
               if old != new]
    old_tail = (FIXTURES / "native_bot_transition_tail_ai_mirror_20261004.inc").read_text().splitlines()[1:]
    tail = members["tail-run1.inc"].decode().splitlines()
    legacy = (FIXTURES / "native_bot_transition_tail_response_20261002.inc").read_text().splitlines()[1:]
    input_difference = [i for i, (old, new) in enumerate(zip(old_tail, tail))
                        if fields(old)[:3] != fields(new)[:3]]
    position_difference = [i for i, (old, new) in enumerate(zip(old_tail, tail))
                           if fields(old)[3:] != fields(new)[3:]]
    selected = [int(fields(row)[3]) for row in tail]
    if not (len(hashes) == 512 and changed == list(range(512)) and
            len(legacy) == 245 and len(tail) == 2151 and
            all(fields(old)[:3] == fields(new)[:3]
                for old, new in zip(legacy, tail[:245])) and
            input_difference[0] == 328 and position_difference[0] == 327 and
            all(actor >= 0 for actor in selected[:2054]) and
            selected[2054:2084] == [-1] * 30 and selected[2084:] == [0] * 67):
        raise RuntimeError("Player-switch replay trajectory changed")
    fixtures = {}
    for kind, expected_frames in (("hashes", 512), ("tail", 2151)):
        raw = members[f"{kind}-run1.inc"]
        path = FIXTURES / f"native_bot_transition_{kind}_player_switch_20261004.inc"
        if len(raw.splitlines()) != expected_frames or path.read_bytes() != HEADER + raw:
            raise RuntimeError(f"Player-switch fixture differs from replay: {kind}")
        fixtures[path.relative_to(ROOT).as_posix()] = digest(path.read_bytes())
    archive_path = BASE / f"{NAME}.tar.gz"
    archive = packed(members)
    archive_path.write_bytes(archive)
    manifest = {
        "format": 1, "id": "bot-selection-player-switch-20261004",
        "historical_reference": previous.relative_to(ROOT).as_posix(),
        "historical_reference_sha256": digest(previous.read_bytes()),
        "source_commit": source_commit,
        "candidate_sources": {name: digest((ROOT / name).read_bytes()) for name in SOURCES},
        "generator_sha256": digest(Path(__file__).read_bytes()),
        "archive": {"path": archive_path.relative_to(ROOT).as_posix(),
                    "sha256": digest(archive),
                    "generator_sha256": digest(members["generator.cpp"])},
        "raw_oracles": {"independent_runs": 2,
                        "hashes_sha256": digest(members["hashes-run1.inc"]),
                        "tail_sha256": digest(members["tail-run1.inc"])},
        "fixtures": fixtures,
        "contract": {"prefix_frames": 512, "tail_frames": 2151,
                     "historical_input_frames": 245,
                     "first_changed_frame_vs_prior": 0,
                     "changed_prefix_hashes_vs_prior": 512,
                     "first_position_divergence_vs_prior": 327,
                     "first_bot_input_divergence_vs_prior": 328,
                     "first_unavailable_tail_frame": 2054,
                     "unavailable_frames": 30, "recovered_frames": 66,
                     "opponent_restart_wait_frames": 0,
                     "emit_assertions": 4921, "normal_assertions": 11610},
    }
    path = BASE / f"{NAME}.json"
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"passed": True, "manifest": path.relative_to(ROOT).as_posix(),
                      "manifest_sha256": digest(path.read_bytes()),
                      "archive_sha256": digest(archive), "independent_runs": 2}))


if __name__ == "__main__":
    main()
