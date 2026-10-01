#!/usr/bin/env python3
"""Summarize recorded touch frames in the shipped animation assets."""

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
ANIMATIONS = ROOT / "engine/data/media/animations"
TOUCH_FRAME = re.compile(rb"extension,football,(\d+),")


def summarize(kind):
    records = []
    for path in sorted((ANIMATIONS / kind).rglob("*.anim")):
        contents = path.read_bytes()
        frames = [int(value) for value in TOUCH_FRAME.findall(contents)]
        if not frames:
            raise RuntimeError(f"Missing touch extension: {path}")
        records.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(contents).hexdigest(),
            "earliest_touch_frame": min(frames),
        })
    if not records:
        raise RuntimeError(f"Missing animation assets: {kind}")
    return {
        "assets": len(records),
        "earliest_frame": min(item["earliest_touch_frame"] for item in records),
        "at_most_5_frames": sum(item["earliest_touch_frame"] <= 5 for item in records),
        "at_most_8_frames": sum(item["earliest_touch_frame"] <= 8 for item in records),
        "records": records,
    }


def main():
    print(json.dumps({
        "format": 1,
        "frame_duration_ms": 10,
        "trap": summarize("trap"),
        "ballcontrol": summarize("ballcontrol"),
    }, indent=2))


if __name__ == "__main__":
    main()
