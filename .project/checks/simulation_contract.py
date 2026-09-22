#!/usr/bin/env python3
"""Require adversarial snapshot recovery and actual EGL/simulation equivalence."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from native_boundary import ROOT, require, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    args = parser.parse_args()
    build = args.build.resolve()
    run(["cmake", "-S", "engine", "-B", build])
    run(["cmake", "--build", build, "-j", "1", "--target", "engine_simulation_contract"])
    environment = dict(os.environ)
    environment.pop("DISPLAY", None)
    results = []
    for seed in (42, 43):
        for variant in ([], ["--reverse"], ["--render"]):
            arguments = [str(build / "bin/engine_simulation_contract"), str(seed), *variant]
            print("Running: " + " ".join(arguments), flush=True)
            output = subprocess.run(arguments, cwd=ROOT, env=environment, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            print(output.stdout, flush=True)
            require(output.returncode == 0, f"Simulation contract exited {output.returncode}")
            result = json.loads(output.stdout.strip().splitlines()[-1])
            minimum = 92 if variant == ["--render"] else 800
            require(result.get("passed") is True and result.get("assertions", 0) >= minimum
                    and result.get("skipped") == 0, "Incomplete simulation contract")
            if variant != ["--render"]:
                require(result.get("collision_workspace") is True,
                        "Missing real collision roster/restore workspace coverage")
            results.append(dict(seed=seed, variant=variant, **{k: v for k, v in result.items() if k != "seed"}))
    print(json.dumps({"passed": True, "assertions": sum(r["assertions"] for r in results),
                      "skipped": 0, "results": results}))


if __name__ == "__main__":
    main()
