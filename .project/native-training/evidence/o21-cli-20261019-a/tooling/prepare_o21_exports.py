"""Export O20 policies using their original strictly compatible native engine."""
import json,os,shlex,subprocess
from pathlib import Path
import quality
from validate import ROOT,sha,source_fingerprint
out=Path('/root/work_space/football-artifacts/o21-policy-exports-20261019-a');out.mkdir(exist_ok=False)
quality.verify(ROOT/'.project/native-training/evidence/two-on-one-quality-20261018-final/report.json')
old=json.loads((ROOT/'.project/native-training/evidence/two-on-one-inference-20261019-a/assessment/protocol.json').read_text())
assert source_fingerprint()==old['source']
build=Path(old['build']);flags={}
for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
    if ' = ' in line:
        k,v=line.split(' = ',1);flags[k]=shlex.split(v)
link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
source=Path(__file__).with_name('export_o20_policy.cpp')
subprocess.run([link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',str(source),'-o',str(out/'export.o')],cwd=build,check=True)
idx=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(idx)==1
link[idx[0]]=str(out/'export.o');link[link.index('-o')+1]=str(out/'export');subprocess.run(link,cwd=build,check=True)
env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
rows=[]
for seed,m in old['models'].items():
    assert sha(Path(m['path']))==m['sha256']
    data=json.loads(subprocess.check_output([str(out/'export'),seed,m['path'],str(out/f'{seed}.fpol')],cwd=build,env=env,text=True))
    assert data['checkpoint_sha256']==m['sha256'] and data['policy_sha256']==sha(out/f'{seed}.fpol')
    rows.append(data);print(seed,flush=True)
(out/'report.json').write_text(json.dumps(dict(passed=True,source=source_fingerprint(),exporter_sha256=sha(source),binary_sha256=sha(out/'export'),original_core_sha256=sha(build/'libfootball_engine.so'),models=rows),indent=2)+'\n')
