"""Validation-only comparison of two deterministic controllers on known broad cases."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

import quality
from validate import ROOT,sha,source_fingerprint
from validate_learning import SEEDS


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    work=parser.parse_args().output.resolve();assert work!=ROOT and ROOT not in work.parents
    work.mkdir(parents=True,exist_ok=False)
    previous=ROOT/'.project/native-training/evidence/two-on-one-broad-20261018-a/assessment'
    old=json.loads((previous/'protocol.json').read_text());before=source_fingerprint();assert before==old['source']
    quality.verify(ROOT/'.project/native-training/evidence/two-on-one-quality-20261018-final/report.json')
    build=Path(old['build']);here=Path(__file__).parent
    files=[Path(__file__),here/'evaluate_two_on_one_inference.cpp',here/'deterministic_inference.hpp',here/'contract_deterministic_inference.cpp']
    for p in files:shutil.copyfile(p,work/p.name)
    tools={p.name:sha(p) for p in files}
    protocol=dict(validation_only=True,candidates=['balanced','repeat8'],seeds=list(SEEDS),
        case_sha256=sha(previous/'cases.txt'),tools=tools,source=before,
        gate='mean>=.80; every seed>=.65 and not worse than matched old argmax by>.05; raw cooperation/joint>=.1',
        selection='Largest eligible validation mean, insertion-order tie; no confirmation opened')
    (work/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    report=dict(passed=False,validation_passed=False,source_before=before,commands=[],candidates={},
        protocol_sha256=sha(work/'protocol.json'),tools=tools)
    env=dict(os.environ,GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'),LD_LIBRARY_PATH=str(build))
    def run(name,argv,environment=env):
        print(name,flush=True)
        with (work/(name+'.log')).open('w') as out:
            result=subprocess.run(list(map(str,argv)),cwd=build,env=environment,stdout=out,stderr=subprocess.STDOUT,timeout=1200)
        report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=result.returncode,sha256=sha(work/(name+'.log'))));assert result.returncode==0,name
    try:
        flags={}
        for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:
                k,v=line.split(' = ',1);flags[k]=shlex.split(v)
        link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
        run('compile-contract',[link[0],'-std=c++23','-O2',here/'contract_deterministic_inference.cpp','-o',work/'contract'])
        run('controller-contract',[work/'contract'])
        run('compile-evaluator',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',here/'evaluate_two_on_one_inference.cpp','-o',work/'evaluate.o'])
        indices=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(indices)==1
        link[indices[0]]=str(work/'evaluate.o');link[link.index('-o')+1]=str(work/'evaluate');run('link',link)
        for mode in protocol['candidates']:
            rows=[]
            for seed in SEEDS:
                model=Path(old['models'][str(seed)]['path']);assert sha(model)==old['models'][str(seed)]['sha256']
                run(f'{mode}-{seed}',[work/'evaluate',seed,model,mode,previous/'cases.txt'],dict(env,FOOTBALL_INFERENCE_RESUME='1'))
                data=[json.loads(x) for x in (work/f'{mode}-{seed}.log').read_text().splitlines()]
                summary=data.pop();assert summary['isolated'] and summary['episodes']==len(data)==200 and summary['version']==2048
                baseline=[json.loads(x) for x in (previous/f'{seed}-trained_argmax.log').read_text().splitlines()][:-1]
                assert all(a['engine_seed']==b['engine_seed'] and a['index']==b['index'] for a,b in zip(data,baseline))
                result=dict(seed=seed,success=sum(e['controlled_score_delta']>0 for e in data)/200,
                    argmax=sum(e['controlled_score_delta']>0 for e in baseline)/200,
                    cooperation=sum(e['completed_passes']>0 for e in data)/200,
                    joint=sum(e['completed_passes']>0 and e['controlled_score_delta']>0 for e in data)/200)
                rows.append(result)
            mean=sum(r['success'] for r in rows)/5
            eligible=mean>=.8 and all(r['success']>=.65 and r['success']>=r['argmax']-.05 and r['cooperation']>=.1 and r['joint']>=.1 for r in rows)
            report['candidates'][mode]=dict(mean=mean,eligible=eligible,seeds=rows)
            (work/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
        eligible=[m for m in protocol['candidates'] if report['candidates'][m]['eligible']]
        report['selected']=max(eligible,key=lambda m:report['candidates'][m]['mean']) if eligible else None
        report['validation_passed']=bool(eligible);report['passed']=True
    except BaseException as e:report['error']=f'{type(e).__name__}: {e}'
    finally:
        report['source_after']=source_fingerprint()
        if report['source_after']!=before or any(sha(p)!=tools[p.name] for p in files):report.update(passed=False,validation_passed=False,error='Source/tools changed')
        (work/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report.get(k) for k in ('passed','validation_passed','selected','candidates','error')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
