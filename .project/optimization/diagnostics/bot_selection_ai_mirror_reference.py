#!/usr/bin/env python3
"""Rebuild the pinned bot-selection oracle after the AI mirror change."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / ".project/optimization/baselines"
FIXTURES = ROOT / "engine/tests/fixtures"
NAME = "bot_selection_ai_mirror_20261004"
SOURCE = ROOT / "engine/tests/engine_native_bot_selection_contract.cpp"
HEADER = b"// Current AI mirror bot replay oracle, generated twice on 2026-10-04.\n"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def packed(entries: dict[str, bytes]) -> bytes:
    members = {
        "manifest.json": (
            json.dumps(
                {
                    "format": "bot-selection-ai-mirror-oracle-v1",
                    "files": {name: digest(data) for name, data in sorted(entries.items())},
                },
                sort_keys=True,
                indent=2,
            ).encode()
            + b"\n"
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


def fields(line: str) -> list[str]:
    return line.strip().rstrip(",").strip("{}").split(",")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build", type=Path, default=Path("/tmp/football-optimization-native")
    )
    args = parser.parse_args()
    exe = (args.build / "bin/engine_native_bot_selection_contract").resolve()
    environment = dict(
        os.environ,
        LD_LIBRARY_PATH=str(args.build.resolve()),
        GFOOTBALL_DATA_DIR=str(ROOT / "engine/data"),
        LIBGL_ALWAYS_SOFTWARE="1",
    )
    environment.pop("LD_PRELOAD", None)
    members = {"generator.cpp": SOURCE.read_bytes()}
    with tempfile.TemporaryDirectory(prefix="football-bot-ai-mirror-oracle-") as directory:
        temporary = Path(directory)
        for run in (1, 2):
            hashes = temporary / f"hashes-run{run}.inc"
            tail = temporary / f"tail-run{run}.inc"
            result = subprocess.run(
                [str(exe), "--emit-reference", str(hashes), str(tail)],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                timeout=60,
            )
            members[f"run{run}.log"] = (
                f"exit={result.returncode}\n".encode() + result.stdout + result.stderr
            )
            if result.returncode:
                raise RuntimeError(members[f"run{run}.log"].decode(errors="replace"))
            members[f"hashes-run{run}.inc"] = hashes.read_bytes()
            members[f"tail-run{run}.inc"] = tail.read_bytes()
    report = json.loads(members["run1.log"].decode().split("\n", 1)[1])
    assert report == json.loads(members["run2.log"].decode().split("\n", 1)[1])
    assert report["recorded_tail_frames"] == 1566
    for kind, frames in (("hashes", 512), ("tail", 1566)):
        first = members[f"{kind}-run1.inc"]
        assert first == members[f"{kind}-run2.inc"]
        assert len(first.splitlines()) == frames
        (FIXTURES / f"native_bot_transition_{kind}_ai_mirror_20261004.inc").write_bytes(
            HEADER + first
        )
    previous = (
        FIXTURES / "native_bot_transition_hashes_response_20261002.inc"
    ).read_text().splitlines()[1:]
    current = members["hashes-run1.inc"].decode().splitlines()
    changed = [i for i, (a, b) in enumerate(zip(previous, current)) if a != b]
    assert len(previous) == len(current) == 512 and changed
    prior_tail = (
        FIXTURES / "native_bot_transition_tail_response_20261002.inc"
    ).read_text().splitlines()[1:]
    current_tail = members["tail-run1.inc"].decode().splitlines()
    assert len(prior_tail) == 245
    assert all(
        fields(a)[:3] == fields(b)[:3]
        for a, b in zip(prior_tail, current_tail[: len(prior_tail)])
    )
    selected = [int(fields(line)[3]) for line in current_tail]
    unavailable = [i for i, actor in enumerate(selected) if actor == -1]
    assert unavailable and any(actor >= 0 for actor in selected[unavailable[-1] + 1 :])
    assert report["unavailable_frames"] == len(unavailable)
    archive_path = BASE / f"{NAME}.tar.gz"
    archive_path.write_bytes(packed(members))

    def relative(path: Path) -> str:
        return path.relative_to(ROOT).as_posix()

    previous_path = BASE / "bot_selection_response_20261002.json"
    source_paths = (
        "engine/src/ai/ai_tactics.cpp",
        "engine/src/ai/ai_tactics.hpp",
        "engine/src/frame_sync/bot_takeover.hpp",
        "engine/src/frame_sync/engine_bot_observer.hpp",
        "engine/src/onthepitch/team.cpp",
    )
    manifest = {
        "format": 1,
        "id": "bot-selection-ai-mirror-20261004",
        "historical_reference": relative(previous_path),
        "historical_reference_sha256": digest(previous_path.read_bytes()),
        "candidate_sources": {
            name: digest((ROOT / name).read_bytes()) for name in source_paths
        },
        "archive": {
            "path": relative(archive_path),
            "sha256": digest(archive_path.read_bytes()),
            "generator_sha256": digest(members["generator.cpp"]),
        },
        "raw_oracles": {
            "independent_runs": 2,
            "hashes_sha256": digest(members["hashes-run1.inc"]),
            "tail_sha256": digest(members["tail-run1.inc"]),
        },
        "fixtures": {
            relative(FIXTURES / f"native_bot_transition_{kind}_ai_mirror_20261004.inc"): digest(
                (FIXTURES / f"native_bot_transition_{kind}_ai_mirror_20261004.inc").read_bytes()
            )
            for kind in ("hashes", "tail")
        },
        "contract": {
            "prefix_frames": 512,
            "tail_frames": len(current_tail),
            "historical_input_frames": len(prior_tail),
            "first_changed_frame_vs_prior": changed[0],
            "changed_prefix_hashes_vs_prior": len(changed),
            "first_unavailable_tail_frame": unavailable[0],
            "unavailable_frames": report["unavailable_frames"],
            "recovered_frames": report["recovered_frames"],
            "opponent_restart_wait_frames": report["opponent_restart_wait_frames"],
            "assertions": report["assertions"],
        },
    }
    path = BASE / f"{NAME}.json"
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(path, digest(path.read_bytes()))
    print(json.dumps(manifest["contract"], sort_keys=True))


if __name__ == "__main__":
    main()
