#!/usr/bin/env python3
"""Run the temporarily approved non-GPU optimization scope."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".project"))
from quality import Program, QualityError  # noqa: E402

TARGETS = ("ms-25.1", "task-26.1.2.1")
DEFERRED_CHECK = "render_regression"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    program = Program(ROOT)
    ordered = program.order(TARGETS)
    blocked = [name for name in ordered
               if DEFERRED_CHECK in program.nodes[name]["checks"]]
    if blocked:
        raise QualityError("Non-GPU scope includes deferred GPU checks: " +
                           ", ".join(blocked))
    if not args.dry_run:
        for target in TARGETS:
            program.run(target)
    states = program.states()
    print(json.dumps({"scope": "non_gpu_20261009", "dry_run": args.dry_run,
                      "targets": {name: states[name] for name in TARGETS},
                      "deferred": {name: states[name] for name in
                                   ("task-24.1.2.2", "ms-24.1",
                                    "task-26.1.2.2", "ms-26.1")}},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except QualityError as error:
        print(f"non_gpu_scope: {error}", file=sys.stderr)
        sys.exit(1)
