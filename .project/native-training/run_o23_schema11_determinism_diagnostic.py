"""Run a bounded, serial Schema11 seed-31415 reproducibility diagnostic."""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

import quality
from validate import ROOT, sha, source_fingerprint


SEED = 31415
UPDATES = 1024
MAX_WALL_SECONDS = 1800
MAX_RSS_BYTES = 512 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024 * 1024


def write(path, value):
  path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def load_rows(path):
  rows = [json.loads(line) for line in path.read_text().splitlines()]
  summary = rows.pop()
  assert summary["complete"] and len(rows) == 200
  return rows


def directory_size(path):
  return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--quality", type=Path, required=True)
  parser.add_argument("--build", type=Path, required=True)
  parser.add_argument("--study", type=Path, required=True)
  parser.add_argument("--output", type=Path, required=True)
  args = parser.parse_args()
  quality_receipt = quality.verify(args.quality / "report.json")
  study = args.study.resolve()
  study_report = json.loads((study / "report.json").read_text())
  assert study_report["passed"] and not study_report["validation_passed"]
  before = source_fingerprint()
  assert before["sha256"] == quality_receipt["source_sha256"]
  assert before == study_report["source_before"]
  build = args.build.resolve()
  binary = build / "bin" / "native_ppo_train"
  assert binary.is_file()
  cases = study / "cases.txt"
  assert len(cases.read_text().splitlines()) == 200
  out = args.output.resolve()
  out.mkdir(parents=True, exist_ok=False)
  frozen = {
      str(Path(__file__).resolve()): sha(Path(__file__)),
      str(binary): sha(binary),
      str(build / "libfootball_engine.so"): sha(build / "libfootball_engine.so"),
      str(cases): sha(cases),
      str(args.quality.resolve() / "report.json"): sha(args.quality.resolve() / "report.json"),
      str(study / "report.json"): sha(study / "report.json"),
  }
  protocol = {
      "source": before,
      "scenario": "2v1_broad_edge_balanced_finisher",
      "seed": SEED,
      "updates": UPDATES,
      "training": {"hidden": 64, "epochs": 4, "minibatch": 64, "rollout": 256,
                   "cadence": 10, "episode_limit": 256, "initial_eval": False,
                   "eval_episodes": 0},
      "budget": {"max_wall_seconds_per_training": MAX_WALL_SECONDS,
                 "max_rss_bytes": MAX_RSS_BYTES, "max_output_bytes": MAX_OUTPUT_BYTES},
      "cases": str(cases),
      "cases_sha256": sha(cases),
      "frozen": frozen,
      "selection": "none; diagnostic only",
      "confirmation_opened": False,
  }
  write(out / "protocol.json", protocol)
  env = dict(os.environ, LD_LIBRARY_PATH=str(build), GFOOTBALL_DATA_DIR=str(ROOT / "engine/data"),
             GFOOTBALL_FONT=str(ROOT / "engine/fonts/AlegreyaSansSC-ExtraBold.ttf"))
  commands = []

  def unchanged():
    assert source_fingerprint() == before
    assert all(sha(Path(path)) == digest for path, digest in frozen.items())

  def run(name, argv, cap):
    started = time.monotonic()
    peak = 0
    stdout = out / f"{name}.log"
    stderr = out / f"{name}.stderr"
    with stdout.open("w") as out_stream, stderr.open("w") as err_stream:
      child = subprocess.Popen(list(map(str, argv)), cwd=build, env=env,
                               stdout=out_stream, stderr=err_stream)
      process = psutil.Process(child.pid)
      reason = None
      while child.poll() is None:
        elapsed = time.monotonic() - started
        try:
          peak = max(peak, process.memory_info().rss)
        except psutil.NoSuchProcess:
          pass
        if elapsed > cap:
          reason = "wall budget"
        elif peak > MAX_RSS_BYTES:
          reason = "rss budget"
        elif directory_size(out) > MAX_OUTPUT_BYTES:
          reason = "output budget"
        if reason:
          child.terminate()
          child.wait(timeout=5)
          break
        time.sleep(0.2)
    seconds = time.monotonic() - started
    commands.append({"name": name, "argv": list(map(str, argv)), "exit_code": child.returncode,
                     "seconds": seconds, "peak_rss": peak, "reason": reason,
                     "stdout_sha256": sha(stdout), "stderr_sha256": sha(stderr)})
    assert reason is None and child.returncode == 0, (name, reason, child.returncode)

  report = {"passed": False, "source_before": before, "protocol_sha256": sha(out / "protocol.json"),
            "quality": quality_receipt, "commands": commands}
  try:
    replicas = []
    for replica in ("a", "b"):
      checkpoint = out / f"seed-{SEED}-{replica}.fppo"
      policy = out / f"seed-{SEED}-{replica}.fpol"
      run(f"train-{replica}", [binary, "--scenario", protocol["scenario"], "--seed", SEED,
                                "--hidden", 64, "--epochs", 4, "--minibatch", 64, "--rollout", 256,
                                "--cadence", 10, "--episode-limit", 256, "--no-initial-eval",
                                "--eval-episodes", 0, "--updates", UPDATES, "--save", checkpoint,
                                "--export-policy", policy], MAX_WALL_SECONDS)
      train = json.loads((out / f"train-{replica}.log").read_text())
      assert train["version"] == UPDATES and train["start_version"] == 0
      assert train["state_sha256"] == sha(checkpoint)
      assert len(train["iterations"]) == UPDATES
      assert all(row["learning_rate"] == .0003 * max(.1, (8193 - row["version"]) / 8192)
                 and row["optimizer_steps"] == 16 and row["transitions"] == 256
                 and all(math.isfinite(row[key]) for key in ("loss", "entropy", "gradient_norm", "parameter_delta"))
                 for row in train["iterations"])
      unchanged()
      replay_name = f"replay-{replica}"
      run(replay_name, [binary, "--inference-mode", "balanced", "--policy", policy,
                        "--inference-cases", cases], 300)
      replicas.append({"replica": replica, "checkpoint": str(checkpoint), "checkpoint_sha256": sha(checkpoint),
                       "policy": str(policy), "policy_sha256": sha(policy), "train": train,
                       "rows": load_rows(out / f"{replay_name}.log")})
      unchanged()
    a, b = replicas
    report.update(
        passed=True,
        checkpoint_sha256_equal=a["checkpoint_sha256"] == b["checkpoint_sha256"],
        policy_sha256_equal=a["policy_sha256"] == b["policy_sha256"],
        training_rows_equal=a["train"]["iterations"] == b["train"]["iterations"],
        replay_rows_equal=a["rows"] == b["rows"],
        replicas=[{key: value for key, value in item.items() if key not in ("train", "rows")} for item in replicas],
    )
    report["deterministic"] = all(report[key] for key in ("checkpoint_sha256_equal", "policy_sha256_equal",
                                                            "training_rows_equal", "replay_rows_equal"))
  except BaseException as error:
    report["error"] = f"{type(error).__name__}: {error}"
  finally:
    report["source_after"] = source_fingerprint()
    report["source_unchanged"] = report["source_after"] == before
    write(out / "report.json", report)
  print(json.dumps({key: report.get(key) for key in ("passed", "deterministic", "error")}), flush=True)
  return 0 if report["passed"] else 1


if __name__ == "__main__":
  raise SystemExit(main())
