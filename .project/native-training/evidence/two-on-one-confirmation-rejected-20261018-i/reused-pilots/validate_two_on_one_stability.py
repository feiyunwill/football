"""Validation-only robustness check on two non-confirmation training seeds."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from validate import ROOT,sha,source_fingerprint,runtime_identity

def read(path):return json.loads(path.read_text())
def mean(values):return sum(values)/len(values)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('pilots','build-root','work-root','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();pilots=args.pilots.resolve();pilot=read(pilots/'report.json')
    selected=pilot['tasks']['2v1']['selected'];choice=pilot['tasks']['2v1']['pilots'][selected]
    assert pilot['passed'] and read(pilots/'protocol.json')['pilot_only']
    assert choice['success']>=.3 and choice['cooperation']>=.1 and choice['cooperative_success']>=.1
    before=source_fingerprint();binary=args.build_root.resolve()/'bin/native_ppo_train';core=args.build_root.resolve()/'libfootball_engine.so'
    assert before==pilot['source_before']==pilot['source_after']
    assert sha(binary)==pilot['binary_sha256'] and sha(core)==pilot['core_sha256']
    work=args.work_root.resolve();output=args.output.resolve()
    assert ROOT not in work.parents and ROOT!=work
    work.mkdir(parents=True,exist_ok=False);output.mkdir(parents=True,exist_ok=False)
    protocol=dict(training_seeds=[19,101],evaluation_seeds=[88174,88175],episodes_per_batch=32,
        selected=selected,updates=1024,rollout=256,hidden=64,epochs=4,minibatch=64,cadence=10,episode_limit=256,
        partition='validation',primary_policy='sample',gates='each seed: success>=.5, cooperation>=.1, joint pass-and-score>=.1; strictly beat own untrained sample and random',
        scope='Validation only. No confirmation seeds or partitions opened. These seeds are not the final five training seeds.')
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    report=dict(passed=False,validation_stable=False,source_before=before,environment_before=runtime_identity(sys.executable),
        binary_sha256=sha(binary),core_sha256=sha(core),pilot_report_sha256=sha(pilots/'report.json'),
        protocol_sha256=sha(output/'protocol.json'),runner_sha256=sha(Path(__file__)),commands=[],seeds=[],selected=selected)
    env=dict(os.environ,GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    def run(name,seed,options):
        argv=[str(binary),'--scenario','2v1','--seed',str(seed),'--hidden','64','--epochs','4','--minibatch','64',
              '--rollout','256','--cadence','10','--episode-limit','256','--no-initial-eval']
        if selected=='checkpoints64':argv+=['--checkpoints']
        argv+=list(map(str,options));print(name,flush=True)
        with (output/(name+'.log')).open('w') as log:
            result=subprocess.run(argv,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=3600)
        report['commands'].append(dict(name=name,argv=argv,exit_code=result.returncode,sha256=sha(output/(name+'.log'))))
        if result.returncode:raise RuntimeError(name+' failed')
        data=read(output/(name+'.log'))
        assert data['native_agents']==2 and data['players']==1 and data['actions']==19 and data['fixed_teammate_builtin_ai']
        assert data['evaluation']['isolated'] and data['state_sha256']==data['state_before_evaluation_sha256']
        assert all(math.isfinite(v) for r in data['iterations'] for v in r.values() if isinstance(v,(int,float)))
        return data
    try:
        for seed in protocol['training_seeds']:
            path=work/f'model-{seed}.fppo';data=run(f'train-{seed}',seed,['--updates',1024,'--eval-episodes',0,'--save',path])
            assert data['version']==1024 and data['total_transitions']==1024*256 and sha(path)==data['state_sha256']
            assert all(r['parameter_delta']>0 for r in data['iterations'])
            trained=[];initial=[];random=[];cooperation=[];joint=[]
            for batch,test_seed in enumerate(protocol['evaluation_seeds']):
                options=['--updates',0,'--eval-partition','validation','--eval-seed',test_seed,'--eval-episodes',32,'--eval-steps',256]
                fresh=run(f'initial-{seed}-b{batch}',seed,options)
                frozen=run(f'frozen-{seed}-b{batch}',seed,[*options,'--load',path])
                assert frozen['state_sha256']==sha(path)
                identity=None
                for document in (fresh,frozen):
                    assert document['evaluation_partition']==1 and document['evaluation_seed']==test_seed
                    for strategy in document['evaluation']['strategies']:
                        rows=strategy['episodes'];assert len(rows)==32 and all(e['terminated']^e['truncated'] for e in rows)
                        keys=[(e['engine_seed'],e['start_index'],e['start_x'],e['start_y']) for e in rows]
                        if identity is None:identity=keys
                        assert keys==identity
                a=next(s['episodes'] for s in frozen['evaluation']['strategies'] if s['name']=='sample')
                b=next(s['episodes'] for s in fresh['evaluation']['strategies'] if s['name']=='sample')
                c=next(s['episodes'] for s in frozen['evaluation']['strategies'] if s['name']=='uniform_random')
                trained += [e['controlled_score_delta']>0 for e in a];initial += [e['controlled_score_delta']>0 for e in b]
                random += [e['controlled_score_delta']>0 for e in c];cooperation += [e['completed_passes']>0 for e in a]
                joint += [e['completed_passes']>0 and e['controlled_score_delta']>0 for e in a]
            row=dict(seed=seed,success=mean(trained),initial=mean(initial),random=mean(random),cooperation=mean(cooperation),
                     cooperative_success=mean(joint),checkpoint=str(path),checkpoint_sha256=sha(path))
            row['stable']=row['success']>=.5 and row['cooperation']>=.1 and row['cooperative_success']>=.1 and row['success']>max(row['initial'],row['random'])
            report['seeds'].append(row);(output/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
        report.update(passed=True,validation_stable=all(r['stable'] for r in report['seeds']))
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint();report['environment_after']=runtime_identity(sys.executable)
        if report['source_after']!=before or report['environment_before']!=report['environment_after'] or sha(binary)!=report['binary_sha256'] or sha(core)!=report['core_sha256'] or sha(Path(__file__))!=report['runner_sha256']:
            report.update(passed=False,validation_stable=False,error='Source, environment, native build or runner changed')
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n');(output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps({k:report[k] for k in ('passed','validation_stable','seeds','error') if k in report}))
    return 0 if report['passed'] and report['validation_stable'] else 1

if __name__=='__main__':raise SystemExit(main())
