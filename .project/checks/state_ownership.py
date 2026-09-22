#!/usr/bin/env python3
"""Exercise cache restoration and real player/official processing on two seeds."""
import json
from pathlib import Path

from native_boundary import require, run


def main():
    build = Path("/tmp/football-optimization-native")
    run(["cmake", "-S", "engine", "-B", build])
    run(["cmake", "--build", build, "-j", "1", "--target", "engine_state_contract"])
    results = []
    for seed in (42, 43):
        output = run([build / "bin/engine_state_contract", seed], capture=True)
        result = json.loads(output.strip().splitlines()[-1])
        require(result["passed"] is True and result["assertions"] >= 4000,
                f"Incomplete engine state contract for seed {seed}")
        results.append(dict(seed=seed, **result))
    print(json.dumps({"passed": True, "assertions": sum(result["assertions"] for result in results),
                      "skipped": 0, "results": results}))


if __name__ == "__main__":
    main()
