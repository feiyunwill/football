"""Verify raw spatial optimization evidence and the actual learner replay."""
import argparse
import json
from pathlib import Path
import subprocess
import quality
import validate

def load(path): return json.loads(path.read_text())
def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('primary','matrix','quality','baseline','ppo','reference','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(); current=validate.source_fingerprint()
    primary=load(args.primary/'report.json'); matrix=load(args.matrix/'report.json')
    decision=load(args.matrix/'decision.json')
    assert decision['accepted'] and decision['complete_matrix']
    assert decision['report_sha256']==validate.sha(args.matrix/'report.json')
    accepted=quality.verify(args.quality/'report.json')
    baseline=load(args.baseline/'baseline.json')
    changed={name for name in set(current['manifest'])|set(baseline['source']['manifest'])
             if current['manifest'].get(name)!=baseline['source']['manifest'].get(name)}
    expected={'engine/CMakeLists.txt','engine/tests/engine_spatial_invalidation_contract.cpp',
        'engine/src/types/spatial.hpp','engine/src/types/spatial.cpp','engine/src/scene/scene3d/node.hpp',
        'engine/src/scene/scene3d/node.cpp','engine/src/scene/objects/geometry.cpp'}
    assert changed==expected,(changed,expected)
    artifacts=matrix['artifacts']
    assert primary['artifacts']==artifacts
    assert matrix['primary_screen']['sha256']==validate.sha(args.primary/'report.json')
    assert baseline==matrix['baseline_manifest']==primary['baseline_manifest']
    assert len(primary['commands'])==32 and len(matrix['commands'])==112
    for directory,run in ((args.primary,primary),(args.matrix,matrix)):
        assert run['passed'] and run['source_before']==run['source_after']==current
        assert run['validator_sha256']==validate.sha(Path(__file__).with_name('benchmark_spatial.py'))
        assert run['probe_sha256']==validate.sha(Path(__file__).with_name('benchmark_candidate_rollout.py'))
        for command in run['commands']:
            assert command['exit_code']==0
            name=Path(command['argv'][command['argv'].index('--output')+1]).stem
            assert validate.sha(directory/(name+'.log'))==command['sha256']
    assert len(primary['all_case_verified_trajectories'])==8
    for key,variants in primary['all_case_verified_trajectories'].items():
        p,c,f=key.split(',')
        for variant,data in variants.items():
            assert data==load(args.primary/f'preverify-p{p}-c{c}-f{f}-{variant}.json')
        assert variants['baseline']['trajectory_sha256']==variants['candidate']['trajectory_sha256']
    seen=set(); affinity=set()
    for w in matrix['workloads']:
        key=(w['players'],w['cadence'],w['feedback']); assert key not in seen; seen.add(key)
        directory=args.primary if key==(11,2,False) else args.matrix
        for variant in ('baseline','candidate'):
            assert len(w['cpu_samples_ns'][variant])==8
            for repeat in range(8):
                name=f'p{key[0]}-c{key[1]}-feedback{int(key[2])}-r{repeat}-{variant}.json'
                data=load(directory/name); affinity.add(data['cpu_affinity'])
                assert data['steps']==1024 and data['cpu_ns']==w['cpu_samples_ns'][variant][repeat]
                assert data['elapsed_ns']==w['samples_ns'][variant][repeat] and data['final_sha256']==w['final_sha256']
        assert w['paired_cpu_speedups']==[a/b for a,b in zip(w['cpu_samples_ns']['baseline'],w['cpu_samples_ns']['candidate'])]
    assert len(seen)==8 and len(affinity)==1
    run=load(args.ppo/'report.json'); reference=load(args.reference/'report.json')
    assert run['passed'] and reference['passed'] and run['source_before']==run['source_after']==current
    assert reference['source_before']==baseline['source']
    for name,digest in baseline['artifacts'].items():
        recorded=next(value for path,value in reference['artifacts'].items() if path.endswith('/'+name))
        assert recorded==digest
    assert run['updates']==reference['updates']==128 and run['transitions']==32768
    assert run['replay_sha256']==reference['replay_sha256']
    assert run['workers_reaped'] and run['exit_codes']==[0]*4
    assert run['parent_before']['fds']==run['parent_after_close']['fds']
    assert run['environment_before']==run['environment_after'] and run['artifacts']==run['artifacts_after']
    for name in ('iterations.jsonl','resources.jsonl'):
        assert validate.sha(args.ppo/name)==run[name+'_sha256']
    assert validate.sha(args.ppo/'latest-checkpoint.json')==run['checkpoint_sha256']
    left=[load_line for load_line in map(json.loads,(args.ppo/'iterations.jsonl').read_text().splitlines())]
    right=list(map(json.loads,(args.reference/'iterations.jsonl').read_text().splitlines()))
    assert len(left)==len(right)==128
    for x,y in zip(left,right): assert (x['version'],x['transitions'],x['update'])==(y['version'],y['transitions'],y['update'])
    assert canonical(load(args.ppo/'latest-checkpoint.json')['state'])==canonical(load(args.reference/'latest-checkpoint.json')['state'])
    stage=Path(next(path for path in run['artifacts'] if path.endswith('/_gameplayfootball.so'))).parent.parent
    for variant,directory in (('baseline',args.baseline),('candidate',stage)):
        for name,digest in artifacts[variant].items(): assert validate.sha(directory/'gfootball_engine'/name)==digest
        link=subprocess.check_output(['ldd',str(directory/'gfootball_engine/_gameplayfootball.so')],text=True)
        assert str(directory/'gfootball_engine/libfootball_engine.so') in link
    for path,digest in run['artifacts'].items(): assert validate.sha(Path(path))==digest
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    result=dict(passed=True,decision='retain_spatial_subtree_invalidation',source_sha256=current['sha256'],
        source_delta=sorted(changed),quality=accepted,performance=decision,
        trajectory_cases=8,actual_ppo_updates=128,actual_ppo_transitions=32768,learner_and_replay_equal=True,
        worker_exit_codes=run['exit_codes'],workers_reaped=True,parent_fds_before=run['parent_before']['fds'],parent_fds_after=run['parent_after_close']['fds'],
        whole_training_speedup_proven=False,
        receipts={str(path):validate.sha(path) for path in (args.primary/'report.json',args.matrix/'report.json',args.matrix/'decision.json',args.quality/'report.json',args.ppo/'report.json',args.reference/'report.json')},
        runner_sha256=validate.sha(Path(__file__)))
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,actual_ppo_updates=128,source_sha256=current['sha256'])))
    return 0
if __name__=='__main__': raise SystemExit(main())
