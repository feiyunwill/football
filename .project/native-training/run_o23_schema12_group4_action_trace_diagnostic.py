"""Trace rejected Schema12 policies on the already-evaluated group-4 cases."""
import argparse,json,os,shlex,subprocess
from pathlib import Path
import quality
from validate import ROOT,sha,source_fingerprint

def write(path,value): path.write_text(json.dumps(value,indent=2)+'\n')
def rows(path): return [json.loads(line) for line in path.read_text().splitlines()]
def main():
  parser=argparse.ArgumentParser(description=__doc__)
  for key in ('quality','build','study','audit','output'):parser.add_argument('--'+key,type=Path,required=True)
  args=parser.parse_args();quality_receipt=quality.verify(args.quality/'report.json');before=source_fingerprint()
  study=args.study.resolve();report=json.loads((study/'report.json').read_text());audit=json.loads((args.audit/'report.json').read_text())
  assert report['passed'] and not report['validation_passed'] and audit['passed'] and not audit['validation_passed']
  assert report['source_before']==report['source_after']==before and audit['source_sha256']==before['sha256']
  selected=[int(line.split()[0]) for line in (study/'cases.txt').read_text().splitlines() if int(line.split()[1])==4]
  assert selected==list(range(160,200))
  build=args.build.resolve();binary=build/'bin/native_ppo_train';helper=Path(__file__).with_name('trace_o23_schema11_actions.cpp');out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
  models={row['seed']:Path(row['policy']) for row in report['models']};assert set(models)=={42,123,2026,31415,271828}
  (out/'selected.txt').write_text(''.join(f'{index}\n' for index in selected))
  flags={}
  for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
    if ' = ' in line:key,value=line.split(' = ',1);flags[key]=shlex.split(value)
  link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text());obj=out/'trace.o';trace=out/'trace';compile_cmd=[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',str(helper),'-o',str(obj)]
  subprocess.run(compile_cmd,cwd=build,check=True);positions=[index for index,item in enumerate(link) if item.endswith('native_ppo_train.cpp.o')];assert len(positions)==1
  link[positions[0]]=str(obj);link[link.index('-o')+1]=str(trace);subprocess.run(link,cwd=build,check=True)
  frozen={str(path.resolve()):sha(path) for path in [Path(__file__),helper,binary,build/'libfootball_engine.so',study/'cases.txt',study/'report.json',args.audit/'report.json',trace,*models.values()]}
  protocol=dict(source=before,quality=quality_receipt,study=str(study),audit=str(args.audit.resolve()),selected=selected,selection='all already-evaluated group-4 cases; mechanism diagnosis only; no candidate selection',helper_build=dict(compile=compile_cmd,link=link,trace_sha256=sha(trace)),frozen=frozen,confirmation_opened=False)
  write(out/'protocol.json',protocol);env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'));commands=[];diagnosis={}
  try:
    for seed,policy in sorted(models.items()):
      log=out/f'trace-{seed}.jsonl';error=out/f'trace-{seed}.stderr';run=subprocess.run([trace,policy,study/'cases.txt',out/'selected.txt'],cwd=build,env=env,capture_output=True,text=True,timeout=300);log.write_text(run.stdout);error.write_text(run.stderr)
      assert run.returncode==0 and not run.stderr;trace_rows=rows(log);assert len(trace_rows)==40 and [row['index'] for row in trace_rows]==selected and all(row['group']==4 for row in trace_rows)
      expected=next(row for row in report['validation'] if row['seed']==seed);assert sum(row['score']>0 for row in trace_rows)==expected['groups'][4]
      initial={str(action):sum(row['actions'][0]==action for row in trace_rows) for action in range(19)};failure_initial={str(action):sum(row['score']<=0 and row['actions'][0]==action for row in trace_rows) for action in range(19)}
      diagnosis[str(seed)]=dict(goals=sum(row['score']>0 for row in trace_rows),failures=sum(row['score']<=0 for row in trace_rows),initial_actions=initial,failure_initial_actions=failure_initial,mean_steps=sum(row['steps'] for row in trace_rows)/40,mean_completed_passes=sum(row['completed_passes'] for row in trace_rows)/40)
      commands.append(dict(seed=seed,exit_code=run.returncode,stdout_sha256=sha(log),stderr_sha256=sha(error)));assert source_fingerprint()==before and all(sha(Path(path))==digest for path,digest in frozen.items())
    result=dict(passed=True,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=commands,selected_cases=40,diagnosis=diagnosis,source_after=source_fingerprint())
  except BaseException as error:result=dict(passed=False,error=f'{type(error).__name__}: {error}',source_before=before,source_after=source_fingerprint(),commands=commands)
  write(out/'report.json',result);print(json.dumps({key:result.get(key) for key in ('passed','error')}));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
