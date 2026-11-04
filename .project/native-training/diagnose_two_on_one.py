"""Run explicit validation-only interventions using the current native build."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
from validate import ROOT,sha,source_fingerprint

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root',type=Path,required=True)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--checkpoints',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();build=args.build_root.resolve();output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).with_suffix('.cpp');before=source_fingerprint();model_sha=sha(args.checkpoint)
    inputs={str(p):sha(p) for p in [Path(__file__),source,args.checkpoint,build/'libfootball_engine.so',build/'bin/native_ppo_train']}
    flags={}
    for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
        if ' = ' in line:
            key,value=line.split(' = ',1);flags[key]=shlex.split(value)
    link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
    obj=output/'probe.o';binary=output/'probe';commands=[]
    def run(name,argv,env=None):
        with (output/(name+'.log')).open('w') as log:
            result=subprocess.run(list(map(str,argv)),cwd=build,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240)
        commands.append(dict(name=name,argv=list(map(str,argv)),exit_code=result.returncode,sha256=sha(output/(name+'.log'))))
        if result.returncode:raise RuntimeError(name+' failed; see raw log')
    report=dict(passed=False,scope='Exploratory validation-only interventions on one shared engine start; no learning acceptance',
                modes=['full_model','scripted_first_pass_then_model','forced_finishing_phase_ball_at_learner','forced_finishing_phase_ball_at_AI_teammate'],
                source_before=before,inputs=inputs,commands=commands)
    try:
        run('compile',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',source,'-o',obj])
        objects=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(objects)==1
        link[objects[0]]=str(obj);link[link.index('-o')+1]=str(binary);run('link',link)
        env=dict(os.environ,GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'),LD_LIBRARY_PATH=str(build))
        run('interventions',[binary,args.checkpoint.resolve(),str(int(args.checkpoints))],env)
        summaries=[json.loads(line) for line in (output/'interventions.log').read_text().splitlines() if json.loads(line).get('summary')]
        assert len(summaries)==4 and sha(args.checkpoint)==model_sha
        report.update(passed=True,summaries=summaries)
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint()
        if report['source_after']!=before or any(sha(Path(p))!=digest for p,digest in inputs.items()):
            report.update(passed=False,error='Source, tooling, model or native build changed')
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','summaries','error') if k in report}))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
