"""Compile/run the original-vs-production controller contract and cost probe."""
import argparse,json,os,shlex,subprocess
from pathlib import Path
from validate import ROOT,sha,source_fingerprint

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
source=Path(__file__).with_name('benchmark_o21_inference.cpp');flags={};build=args.build.resolve();before=source_fingerprint()
for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
    if ' = ' in line:
        k,v=line.split(' = ',1);flags[k]=shlex.split(v)
link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
subprocess.run([link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',str(source),'-o',str(out/'micro.o')],cwd=build,check=True)
index=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(index)==1
link[index[0]]=str(out/'micro.o');link[link.index('-o')+1]=str(out/'micro');subprocess.run(link,cwd=build,check=True)
policy=Path('/root/work_space/football-artifacts/o21-policy-exports-20261019-a/42.fpol')
data=json.loads(subprocess.check_output([str(out/'micro'),str(policy)],cwd=out,env=dict(os.environ,LD_LIBRARY_PATH=str(build)),text=True))
assert data['contract_passed'] and data['o20_equal_decisions']==10000 and source_fingerprint()==before
data.update(source_sha256=before['sha256'],tool_sha256=sha(source),binary_sha256=sha(out/'micro'),policy_sha256=sha(policy),scope='Synthetic observation; forward+distribution+action choice,5 repeats x20000 decisions/mode; modes interleaved in fixed order')
(out/'report.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data),flush=True)
