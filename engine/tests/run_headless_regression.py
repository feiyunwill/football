#!/usr/bin/env python3
"""Run independent native matches and verify snapshot restore/replay (2026-09-09)."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--frames", type=int, default=1000)
    args = parser.parse_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")
    binary = args.binary.resolve()
    root = Path(__file__).resolve().parents[2]
    results = []
    for seed in (42, 43):
        hashes = []
        for _ in range(2):
            run = subprocess.run(
                [str(binary), "2", "2", str(seed), str(args.frames), "--verify-rollback"],
                cwd=root, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=120,
            )
            matches = re.findall(r"Final state hash: ([0-9a-f]{16})", run.stdout)
            if run.returncode or len(matches) != 1 or "Snapshot restore/replay verified" not in run.stdout:
                raise RuntimeError(f"Native match failed (seed={seed}, exit={run.returncode}):\n{run.stdout}")
            hashes.append(matches[0])
        if hashes[0] != hashes[1]:
            raise RuntimeError(f"Independent processes diverged (seed={seed}): {hashes}")
        results.append(dict(seed=seed, frames=args.frames, slots=[2, 2],
                            independent_processes=2, snapshot_replay=True, hash=hashes[0]))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
