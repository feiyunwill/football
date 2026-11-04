"""Independently audit the source-independent Schema11 action-trace diagnostic."""
import argparse, hashlib, json
from pathlib import Path

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
  parser=argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--diagnostic",type=Path,required=True)
  parser.add_argument("--output",type=Path,required=True)
  args=parser.parse_args(); diagnostic=args.diagnostic.resolve(); output=args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
  report=json.loads((diagnostic/"report.json").read_text()); protocol=json.loads((diagnostic/"protocol.json").read_text())
  assert report["passed"] and report["source_unchanged"] and report["source_before"]==report["source_after"]
  assert report["protocol_sha256"]==sha(diagnostic/"protocol.json")
  assert protocol["selection"]=="none; mechanism diagnostic only" and not protocol["confirmation_opened"]
  assert report["selected_cases"]==35 and protocol["selected"]==sorted(protocol["selected"]) and len(protocol["selected"])==35
  assert [row["seed"] for row in report["commands"]]==[42,123,2026,31415,271828]
  assert all(row["exit_code"]==0 and sha(diagnostic/f"trace-{row['seed']}.jsonl")==row["stdout_sha256"] and sha(diagnostic/f"trace-{row['seed']}.stderr")==row["stderr_sha256"] for row in report["commands"])
  assert set(report["comparisons"])=={"42","123","2026","271828"}
  assert all(0<=row["first_action_equal"]<=35 and 0<=row["full_observed_prefix_equal"]<=35 for row in report["comparisons"].values())
  assert all(sha(Path(path))==digest for path,digest in protocol["frozen"].items())
  result=dict(passed=True,selected_cases=35,focus_seed=31415,comparisons=report["comparisons"],report_sha256=sha(diagnostic/"report.json"),protocol_sha256=sha(diagnostic/"protocol.json"))
  (output/"report.json").write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result))
if __name__=="__main__": main()
