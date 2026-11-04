"""Independently audit the bounded Schema11 seed-31415 reproducibility diagnostic."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--diagnostic", type=Path, required=True)
  parser.add_argument("--output", type=Path, required=True)
  args = parser.parse_args()
  diagnostic = args.diagnostic.resolve()
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  report = json.loads((diagnostic / "report.json").read_text())
  protocol = json.loads((diagnostic / "protocol.json").read_text())
  assert report["passed"] and report["source_unchanged"]
  assert report["protocol_sha256"] == sha(diagnostic / "protocol.json")
  assert protocol["selection"] == "none; diagnostic only" and not protocol["confirmation_opened"]
  assert protocol["seed"] == 31415 and protocol["updates"] == 1024
  assert protocol["budget"]["max_wall_seconds_per_training"] <= 1800
  assert all(command["reason"] is None and command["exit_code"] == 0 for command in report["commands"])
  assert [command["name"] for command in report["commands"]] == ["train-a", "replay-a", "train-b", "replay-b"]
  assert all(command["peak_rss"] <= protocol["budget"]["max_rss_bytes"] for command in report["commands"])
  for path, digest in protocol["frozen"].items():
    assert sha(Path(path)) == digest
  result = {
      "passed": True,
      "diagnostic_passed": report["passed"],
      "deterministic": report["deterministic"],
      "checkpoint_sha256_equal": report["checkpoint_sha256_equal"],
      "policy_sha256_equal": report["policy_sha256_equal"],
      "training_rows_equal": report["training_rows_equal"],
      "replay_rows_equal": report["replay_rows_equal"],
      "report_sha256": sha(diagnostic / "report.json"),
      "protocol_sha256": sha(diagnostic / "protocol.json"),
  }
  (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
  print(json.dumps(result))


if __name__ == "__main__":
  main()
