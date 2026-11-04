"""Actual process continuation for all five modes and an episode boundary."""
import argparse,json,os,subprocess
from pathlib import Path
from validate import ROOT,sha,source_fingerprint

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);before=source_fingerprint()
binary=args.build/'bin/native_ppo_train';policy=Path('/root/work_space/football-artifacts/o21-policy-exports-20261019-a/42.fpol')
old=ROOT/'.project/native-training/evidence/two-on-one-inference-20261019-a/assessment'
cases=out/'cases.txt';cases.write_text('\n'.join((old/'cases.txt').read_text().splitlines()[:2])+'\n')
env=dict(os.environ,LD_LIBRARY_PATH=str(args.build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
commands=[]
def run(name,mode,extra=()):
    print(name,flush=True)
    result=subprocess.run([str(binary),'--inference-mode',mode,'--policy',str(policy),'--inference-cases',str(cases),*map(str,extra)],env=env,capture_output=True,timeout=120)
    (out/(name+'.log')).write_bytes(result.stdout);(out/(name+'.stderr')).write_bytes(result.stderr)
    commands.append(dict(name=name,exit_code=result.returncode,sha256=sha(out/(name+'.log'))));assert result.returncode==0,result.stderr.decode()
    return result.stdout.splitlines(keepends=True)[:-1]
for mode in ('balanced','argmax','sample','uniform_random','builtin_ai'):
    full=run(mode+'-full',mode);state=out/(mode+'.fifs')
    prefix=run(mode+'-prefix',mode,('--inference-decisions',8,'--inference-state-out',state))
    tail=run(mode+'-tail',mode,('--inference-state-in',state));assert full==prefix+tail
full=run('boundary-full','balanced');steps=json.loads(full[0])['steps'];state=out/'boundary.fifs'
prefix=run('boundary-prefix','balanced',('--inference-decisions',steps,'--inference-state-out',state))
metadata=state.read_bytes().split(b'\n',3)[2].split();assert metadata[3:5]==[b'1',b'0']
tail=run('boundary-tail','balanced',('--inference-state-in',state));assert full==prefix+tail
assert source_fingerprint()==before
(out/'report.json').write_text(json.dumps(dict(passed=True,modes_resumed=5,episode_boundary_resumed=True,source_sha256=before['sha256'],commands=commands),indent=2)+'\n')
