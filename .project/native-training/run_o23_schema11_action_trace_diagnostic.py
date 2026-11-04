"""Trace frozen Schema11 final policies on already-evaluated divergent starts."""
import argparse, json, os, shlex, subprocess
from pathlib import Path
import quality
from validate import ROOT, sha, source_fingerprint

def write(path, value): path.write_text(json.dumps(value, indent=2) + "\n")
def read_rows(path): return [json.loads(line) for line in path.read_text().splitlines()]

def main():
  parser=argparse.ArgumentParser(description=__doc__)
  for key in ("quality","build","study","diagnosis","output"): parser.add_argument("--"+key,type=Path,required=True)
  args=parser.parse_args(); quality_receipt=quality.verify(args.quality/"report.json")
  before=source_fingerprint(); assert before["sha256"]==quality_receipt["source_sha256"]
  study=args.study.resolve(); report=json.loads((study/"report.json").read_text())
  diagnosis=json.loads((args.diagnosis/"report.json").read_text())
  assert report["passed"] and not report["validation_passed"] and report["source_before"]==before
  focus=diagnosis["focus_seed"]; assert focus==31415 and diagnosis["case_identity_equal"]
  selected=sorted(row["index"] for row in diagnosis["focus_vs_other_seed_majority"]["cases"]
                  if not row["focus_won"] and row["other_wins"]>=3)
  assert len(selected)==35 and len(set(selected))==35
  build=args.build.resolve(); binary=build/"bin/native_ppo_train"; helper=Path(__file__).with_name("trace_o23_schema11_actions.cpp")
  out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False); cases=study/"cases.txt"
  models={row["seed"]:Path(row["policy"]) for row in report["models"]}
  assert set(models)=={42,123,2026,31415,271828}
  with (out/"selected.txt").open("w") as stream:
    for index in selected: stream.write(f"{index}\n")
  flags={}
  for line in (build/"CMakeFiles/native_ppo_train.dir/flags.make").read_text().splitlines():
    if " = " in line: key,value=line.split(" = ",1); flags[key]=shlex.split(value)
  link=shlex.split((build/"CMakeFiles/native_ppo_train.dir/link.txt").read_text()); obj=out/"trace.o"; trace=out/"trace"
  compile_cmd=[link[0],*flags["CXX_DEFINES"],*flags["CXX_INCLUDES"],*flags["CXX_FLAGS"],"-c",str(helper),"-o",str(obj)]
  subprocess.run(compile_cmd,cwd=build,check=True)
  positions=[i for i,item in enumerate(link) if item.endswith("native_ppo_train.cpp.o")]; assert len(positions)==1
  link[positions[0]]=str(obj); link[link.index("-o")+1]=str(trace); subprocess.run(link,cwd=build,check=True)
  frozen={str(path.resolve()):sha(path) for path in [Path(__file__),helper,binary,build/"libfootball_engine.so",cases,args.diagnosis/"report.json",trace,*models.values()]}
  protocol=dict(source=before,quality=quality_receipt,study=str(study),diagnosis=str(args.diagnosis.resolve()),selected=selected,
                helper_build=dict(compile=compile_cmd,link=link,trace_sha256=sha(trace)),frozen=frozen,selection="none; mechanism diagnostic only",confirmation_opened=False)
  write(out/"protocol.json",protocol); env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/"engine/data"),GFOOTBALL_FONT=str(ROOT/"engine/fonts/AlegreyaSansSC-ExtraBold.ttf")); commands=[]
  def unchanged(): assert source_fingerprint()==before and all(sha(Path(path))==digest for path,digest in frozen.items())
  traces={}
  try:
    for seed in sorted(models):
      log=out/f"trace-{seed}.jsonl"; error=out/f"trace-{seed}.stderr"
      result=subprocess.run([trace,models[seed],cases,out/"selected.txt"],cwd=build,env=env,capture_output=True,text=True,timeout=300)
      log.write_text(result.stdout); error.write_text(result.stderr)
      assert result.returncode==0 and not result.stderr
      rows=read_rows(log); assert len(rows)==len(selected) and [row["index"] for row in rows]==selected
      assert all(1<=len(row["actions"])<=8 for row in rows)
      commands.append(dict(seed=seed,exit_code=result.returncode,stdout_sha256=sha(log),stderr_sha256=sha(error)))
      traces[seed]=rows; unchanged()
    focus_rows={row["index"]:row for row in traces[focus]}; comparisons={}
    for seed, rows in traces.items():
      if seed==focus: continue
      peer={row["index"]:row for row in rows}
      comparisons[str(seed)]=dict(first_action_equal=sum(focus_rows[i]["actions"][0]==peer[i]["actions"][0] for i in selected),
        full_observed_prefix_equal=sum(focus_rows[i]["actions"]==peer[i]["actions"] for i in selected),
        focus_initial_actions={str(action):sum(row["actions"][0]==action for row in focus_rows.values()) for action in range(19)},
        peer_initial_actions={str(action):sum(row["actions"][0]==action for row in peer.values()) for action in range(19)})
    result=dict(passed=True,source_before=before,protocol_sha256=sha(out/"protocol.json"),commands=commands,selected_cases=len(selected),focus_seed=focus,comparisons=comparisons,source_after=source_fingerprint())
    result["source_unchanged"]=result["source_before"]==result["source_after"]
  except BaseException as error:
    result=dict(passed=False,error=f"{type(error).__name__}: {error}",source_before=before,source_after=source_fingerprint(),commands=commands)
  write(out/"report.json",result); print(json.dumps({key:result.get(key) for key in ("passed","error")})); return 0 if result["passed"] else 1
if __name__=="__main__": raise SystemExit(main())
