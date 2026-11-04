"""One frozen deterministic controller, fresh registered confirmation; no tuning."""
import argparse
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess

import quality
from validate import ROOT, sha, source_fingerprint
from validate_learning import SEEDS, paired_interval
from assess_two_on_one_generalization import GROUPS, MASK


def read(p):
    return json.loads(p.read_text())


def write(p, data):
    p.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args(); out=args.output.resolve()
    assert ROOT != out and ROOT not in out.parents
    validation=Path('/tmp/football-inference-validation-20261019-c')
    decision=read(validation/'report.json')
    assert decision['passed'] and decision['validation_passed']
    selected=decision['selected']; assert selected=='balanced'
    old=ROOT/'.project/native-training/evidence/two-on-one-broad-20261018-a/assessment'
    origin=read(old/'protocol.json'); build=Path(origin['build'])
    before=source_fingerprint(); assert before==origin['source']==decision['source_after']
    quality.verify(ROOT/'.project/native-training/evidence/two-on-one-quality-20261018-final/report.json')
    out.mkdir(parents=True, exist_ok=False)
    here=Path(__file__).parent
    tools=[here/n for n in ('confirm_two_on_one_inference.py','evaluate_two_on_one_inference.cpp','deterministic_inference.hpp','contract_deterministic_inference.cpp')]
    for p in tools: shutil.copyfile(p,out/p.name)
    for name in ('evaluate','contract'): shutil.copy2(validation/name,out/name)
    for name,h in decision['tools'].items(): assert sha(here/name)==h
    forbidden=set(); old_geometry=set()
    for p in (ROOT/'.project/native-training/evidence').rglob('cases.json'):
        data=read(p)
        if not isinstance(data,list): continue
        for c in data:
            if 'engine_seed' in c: forbidden.add(c['engine_seed'])
            if all(k in c for k in ('attacker','teammate','defender')):
                old_geometry.add(tuple(c['attacker']+c['teammate']+c['defender']))
    for p in (ROOT/'.project/native-training/evidence').glob('two-on-one*/test-2v1-*.log'):
        data=read(p)
        for s in data.get('evaluation',{}).get('strategies',[]):
            forbidden.update(e['engine_seed'] for e in s['episodes'])
    rng=random.Random(20261019020); cases=[]; geometries=set(old_geometry); used=set(forbidden)
    for group in range(5):
        for _ in range(40):
            ax=rng.uniform(.44,.68); ay=rng.uniform(-.22,.22); gap=rng.uniform(.12,.20)
            if group==1: ax=rng.uniform(.28,.44)
            if group==2: ay=rng.choice((-1,1))*rng.uniform(.22,.34)
            if group==3: gap=rng.uniform(.06,.12)
            tx=ax+rng.uniform(.08,.18); ty=(-1 if ay>0 else 1)*rng.uniform(.12,.26)
            if group==4:
                tx=ax+rng.uniform(.025,.21); ty=rng.uniform(-.32,.32)
                if abs(ty-ay)<.08: ty=-.24 if ay>=0 else .24
            coords=[round(v,6) for v in (ax,ay,tx,ty,ax+gap,ay*.25+rng.uniform(-.06,.06))]
            assert tuple(coords) not in geometries; geometries.add(tuple(coords))
            assert all(abs(coords[0]-(.44+.06*i+.0125*p))>1e-5 or abs(coords[1]-(-.16+.16*j+.0125*p))>1e-5 for p in range(7) for i in range(4) for j in range(3))
            seed=rng.randrange(1,2000000001)
            while seed in used: seed=rng.randrange(1,2000000001)
            used.add(seed); index=len(cases)
            cases.append(dict(index=index,group=group,group_name=GROUPS[group],engine_seed=seed,
                action_seed=(1220401^0x13198A2E03707344^(index*0x9E3779B97F4A7C15))&MASK,
                attacker=coords[:2],teammate=coords[2:4],defender=coords[4:]))
    write(out/'cases.json',cases)
    (out/'cases.txt').write_text(''.join(' '.join(map(str,[c['index'],c['group'],0,c['engine_seed'],c['action_seed'],*c['attacker'],*c['teammate'],*c['defender']]))+'\n' for c in cases))
    frozen={str(p):sha(p) for p in [*tools,validation/'report.json',out/'cases.json',out/'cases.txt',out/'evaluate',out/'contract',build/'libfootball_engine.so',build/'bin/native_ppo_train',build/'CMakeFiles/native_ppo_train.dir/flags.make',build/'CMakeFiles/native_ppo_train.dir/link.txt']}
    frozen.update({m['path']:m['sha256'] for m in origin['models'].values()})
    protocol=dict(selected=selected,validation_sha256=sha(validation/'report.json'),source=before,
        models=origin['models'],build=str(build),frozen=frozen,seed=20261019020,
        groups=list(GROUPS),cases=200,primary_episodes=1000,forbidden_recorded_seeds=len(forbidden),
        modes=[selected,'argmax','sample','uniform_random','builtin_ai'],
        gates=dict(mean_min=.8,seed_min=.65,seed_vs_argmax_min=-.05,vs_argmax_ci_low_min=0,
            mean_vs_sample_min=-.05,cooperation_min=.1,joint_min=.1),
        statistics='10000 crossed paired bootstrap draws RNG20261015',
        scope='Five bounded geometry families; one frozen adapter; unchanged models and production source')
    write(out/'protocol.json',protocol)
    report=dict(passed=False,confirmation_passed=False,protocol_sha256=sha(out/'protocol.json'),seeds=[],commands=[])
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'),FOOTBALL_INFERENCE_RESUME='1')
    final=[]; greedy=[]
    try:
        for seed in SEEDS:
            data={}
            for mode in protocol['modes']:
                name=f'{seed}-{mode}'; print(name,flush=True)
                with (out/(name+'.log')).open('w') as stream:
                    result=subprocess.run([str(out/'evaluate'),str(seed),origin['models'][str(seed)]['path'],mode,str(out/'cases.txt')],cwd=build,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
                report['commands'].append(dict(name=name,exit_code=result.returncode,sha256=sha(out/(name+'.log')))); assert result.returncode==0,name
                rows=[json.loads(x) for x in (out/(name+'.log')).read_text().splitlines()]; summary=rows.pop()
                assert summary['isolated'] and summary['version']==2048 and summary['transitions']==524288 and summary['episodes']==len(rows)==200
                for e,c in zip(rows,cases):
                    assert e['index']==c['index'] and e['group']==c['group'] and e['engine_seed']==c['engine_seed']
                    assert abs(e['start_x']-c['attacker'][0]-.02)<1e-6 and abs(e['start_y']-c['attacker'][1])<1e-6
                    assert e['terminated']^e['truncated'] and 0<=e['completed_passes']<=e['pass_requests']<=e['steps']<=256
                    assert math.isfinite(e['reward']) and math.isfinite(e['controlled_score_delta'])
                data[mode]=rows
            scores={m:[int(e['controlled_score_delta']>0) for e in rows] for m,rows in data.items()}
            row=dict(seed=seed,rates={m:sum(v)/200 for m,v in scores.items()},
                cooperation=sum(e['completed_passes']>0 for e in data[selected])/200,
                joint=sum(e['completed_passes']>0 and e['controlled_score_delta']>0 for e in data[selected])/200)
            report['seeds'].append(row); final.append(scores[selected]); greedy.append(scores['argmax'])
            write(out/'progress.json',report)
        report['means']={m:sum(r['rates'][m] for r in report['seeds'])/5 for m in protocol['modes']}
        report['versus_argmax']=paired_interval(final,greedy)
        report['confirmation_passed']=(report['means'][selected]>=.8 and report['means'][selected]>=report['means']['sample']-.05 and report['versus_argmax']['low']>0 and all(r['rates'][selected]>=.65 and r['rates'][selected]>=r['rates']['argmax']-.05 and r['cooperation']>=.1 and r['joint']>=.1 for r in report['seeds']))
        report['passed']=True
    except BaseException as e: report['error']=f'{type(e).__name__}: {e}'
    finally:
        report['source_after']=source_fingerprint()
        if before!=report['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()): report.update(passed=False,confirmation_passed=False,error='Frozen inputs changed')
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','confirmation_passed','means','versus_argmax','error')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
