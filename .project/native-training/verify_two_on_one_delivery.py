"""Replay every held-out model result and resumed update from relocated delivery."""
import argparse
import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from validate import ROOT, sha, source_fingerprint
from validate_learning import SEEDS, TEST_SEEDS


def read(path):
    return json.loads(path.read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,required=True)
    parser.add_argument('--delivery',type=Path,required=True,help='Passing exact-current delivery report')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    study_root=args.study.resolve(); study=read(study_root/'report.json')
    delivery=read(args.delivery.resolve())
    protocol=read(study_root/'protocol.json')
    test_seeds=protocol['test_seeds'];partition=protocol.get('evaluation_partition','test')
    assert study['passed'] and study['learning_passed'] and delivery['passed']
    current=source_fingerprint()
    assert study['source_before']==study['source_after']==delivery['source_before']==delivery['source_after']==current
    package=Path(delivery['native_package']['path']).resolve()
    for name,digest in delivery['native_package']['manifest']['files'].items():
        assert sha(package/name)==digest
    models=package/'study-models'; models.mkdir(exist_ok=False)
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    clean={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH') and not k.startswith('GFOOTBALL_')}
    reference_env=dict(clean,GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    commands=[]; checks=[]
    shell=['#!/bin/sh','set -eu','bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)']
    def run(name,command,environment):
        print(name,flush=True)
        log=output/(name+'.json')
        with log.open('w') as stream:
            result=subprocess.run(list(map(str,command)),cwd=output,env=environment,stdout=stream,stderr=subprocess.PIPE,timeout=1800,text=True)
        (output/(name+'.stderr')).write_text(result.stderr)
        commands.append(dict(name=name,argv=list(map(str,command)),exit_code=result.returncode,sha256=sha(log)))
        if result.returncode:raise RuntimeError(name+': '+result.stderr)
        value=read(log)
        assert value['evaluation']['isolated'] and value['state_before_evaluation_sha256']==value['state_sha256']
        return value
    report=dict(passed=False,source_before=current,study_report_sha256=sha(study_root/'report.json'),
                delivery_report_sha256=sha(args.delivery),commands=commands,models=checks,
                verifier_sha256=sha(Path(__file__)))
    try:
        for task,record in study['tasks'].items():
            assert task=='2v1'
            assert record['selected'] in ('sparse64','checkpoints64')
            assert [r['seed'] for r in record['final']]==list(SEEDS)
            for row in record['final']:
                seed=row['seed'];name=f'{task}-{seed}'
                source=Path(row['checkpoint']);assert source.read_bytes()[:4]==b'FPPO' and source.stat().st_size<=32*1024*1024
                assert sha(source)==row['checkpoint_sha256']
                target=models/(name+'.fppo');shutil.copyfile(source,target)
                common=['--scenario',task,'--seed',str(seed),'--hidden','64','--cadence','10','--episode-limit','256',
                        '--rollout','256','--epochs','4','--minibatch','64','--no-initial-eval']
                if record['selected']=='checkpoints64':common+=['--checkpoints']
                frozen=[]
                for batch,test_seed in enumerate(test_seeds):
                    options=['--updates','0','--eval-partition',partition,'--eval-seed',str(test_seed),'--eval-episodes','50','--eval-steps','256']
                    original=read(study_root/f'test-{task}-{seed}-b{batch}.log')
                    replay=run(f'frozen-{name}-b{batch}',[package/'native_ppo_train',*common,*options,'--load',target],clean)
                    assert replay['state_sha256']==row['checkpoint_sha256']
                    assert replay['evaluation']==original['evaluation']
                    frozen.append(sha(output/f'frozen-{name}-b{batch}.json'))
                    shell.append('"$bundle/native_ppo_train" '+shlex.join(common+options)+' --load "$bundle/study-models/'+name+'.fppo"')
                training_name=f'final-train-{task}-{seed}'
                reference=next(c['argv'][0] for c in study['commands'] if c['name']==training_name)
                a,b=output/(name+'-reference.fppo'),output/(name+'-delivered.fppo')
                ref=run('resume-reference-'+name,[reference,*common,'--updates','1','--eval-episodes','0','--load',source,'--save',a],reference_env)
                delivered=run('resume-delivered-'+name,[package/'native_ppo_train',*common,'--updates','1','--eval-episodes','0','--load',target,'--save',b],clean)
                assert a.read_bytes()==b.read_bytes() and ref['iterations']==delivered['iterations']
                checks.append(dict(task=task,seed=seed,path=str(target),sha256=sha(target),frozen_batches=frozen,
                                   resumed_sha256=sha(a),resumed_bytes_equal=True))
        script=package/'reproduce-generalization.sh';script.write_text('\n'.join(shell)+'\n');script.chmod(0o755)
        subprocess.run(['sh','-n',script],check=True)
        shutil.copyfile(study_root/'protocol.json',models/'protocol.json')
        portable=copy.deepcopy(study['tasks'])
        for task,record in portable.items():
            for row in record['final']:row['checkpoint']=f"{task}-{row['seed']}.fppo"
        (models/'results.json').write_text(json.dumps(dict(tasks=portable,primary_policy=protocol.get('primary_policy','argmax'),scope='Bounded2v1 task with fixed learning attacker; not11v11 competence'),indent=2)+'\n')
        (models/'manifest.json').write_text(json.dumps(dict(source_sha256=current['sha256'],study_report_sha256=sha(study_root/'report.json'),
            files={p.name:sha(p) for p in models.iterdir() if p.is_file()},reproduction_script_sha256=sha(script)),indent=2)+'\n')
        report.update(passed=True,frozen_episodes_verified=len(checks)*200,resumed_models_verified=len(checks),
                      package=str(package),models_manifest_sha256=sha(models/'manifest.json'),script_sha256=sha(script))
    except BaseException as error:
        report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint()
        if report['source_after']!=current or report['verifier_sha256']!=sha(Path(__file__)):
            report.update(passed=False,error='Source or verifier changed')
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=report['passed'],models=len(checks),error=report.get('error'))))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
