"""Gated harder2v1 diagnostics; never substitutes for primary confirmation."""
import argparse,json,os,random,subprocess
from pathlib import Path
import numpy as np
from validate import ROOT,sha,source_fingerprint,runtime_identity

SEEDS=(42,123,2026,31415,271828)
GROUPS=('deep_attack','very_wide','tight_defender','trailing_support','combined_pressure')
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('confirmation','audit','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();cp=read(args.confirmation/'protocol.json');cr=read(args.confirmation/'report.json');ar=read(args.audit/'report.json')
    assert cr['passed'] and cr['confirmation_passed'] and ar['passed'] and ar['confirmation_passed']
    assert ar['report_sha256']==sha(args.confirmation/'report.json')
    before=source_fingerprint();assert before==cr['source_after']==cp['source']
    assert all(sha(Path(p))==h for p,h in cp['frozen'].items())
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    corpus=args.confirmation/'forbidden-engine-seeds.u32le';excluded=np.fromfile(corpus,dtype='<u4')
    assert np.all(excluded[:-1]<excluded[1:]);used={c['engine_seed'] for c in read(args.confirmation/'cases.json')}
    rng=random.Random(20261020027);cases=[]
    for group,name in enumerate(GROUPS):
        for _ in range(20):
            ax=rng.uniform(.44,.68);ay=rng.uniform(-.22,.22);gap=rng.uniform(.12,.20)
            if group==0:ax=rng.uniform(.25,.279)
            if group==4:ax=rng.uniform(.38,.43)
            if group in (1,4):ay=rng.choice((-1,1))*rng.uniform(.35,.395)
            if group in (2,4):gap=rng.uniform(.025,.055)
            tx=ax+rng.uniform(.08,.18);ty=(-1 if ay>0 else 1)*rng.uniform(.12,.26)
            if group in (3,4):tx=ax-rng.uniform(.04,.12)
            values=[round(v,6) for v in (ax,ay,tx,ty,ax+gap,ay*.25+rng.uniform(-.06,.06))]
            seed=rng.randrange(1,2000000001);i=np.searchsorted(excluded,seed)
            while seed in used or (i<excluded.size and int(excluded[i])==seed):
                seed=rng.randrange(1,2000000001);i=np.searchsorted(excluded,seed)
            used.add(seed);index=len(cases)
            cases.append(dict(index=index,group=group,group_name=name,engine_seed=seed,
                action_seed=(20261020027^0x13198A2E03707344^(index*0x9E3779B97F4A7C15))&((1<<64)-1),
                attacker=values[:2],teammate=values[2:4],defender=values[4:]))
    write(out/'cases.json',cases)
    (out/'cases.txt').write_text(''.join(' '.join(map(str,[c['index'],c['group'],0,c['engine_seed'],c['action_seed'],*c['attacker'],*c['teammate'],*c['defender']]))+'\n' for c in cases))
    build=Path(cp['build']);binary=build/'bin/native_ppo_train'
    files=[Path(__file__),out/'cases.json',out/'cases.txt',args.confirmation/'report.json',args.confirmation/'protocol.json',args.audit/'report.json',binary,build/'libfootball_engine.so']
    files.extend(Path(cp['models'][str(seed)][label]['path']) for seed in SEEDS for label in ('candidate','old_balanced'))
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,frozen=frozen,environment=runtime_identity(os.sys.executable),generation_seed=20261020027,
        groups=list(GROUPS),cases_per_group=20,seeds=list(SEEDS),modes=['candidate','old_balanced','builtin_ai'],
        max_seconds_per_evaluation=300,selection='None. Frozen primary models only.',
        scope='Harder2v1 descriptive diagnostics. Case seed exclusions reuse audited primary corpus; no primary acceptance gate or general2v2 claim.')
    write(out/'protocol.json',protocol);report=dict(passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=[],results=[])
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    try:
        for seed in SEEDS:
            for label in protocol['modes']:
                policy=cp['models'][str(seed)]['candidate' if label=='builtin_ai' else label]
                assert sha(Path(policy['path']))==policy['sha256']
                name=f'{label}-{seed}';print(name,flush=True)
                argv=[str(binary),'--inference-mode','builtin_ai' if label=='builtin_ai' else 'balanced','--policy',policy['path'],'--inference-cases',str(out/'cases.txt')]
                with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors:
                    result=subprocess.run(argv,cwd=out,env=env,stdout=stream,stderr=errors,timeout=300)
                report['commands'].append(dict(name=name,argv=argv,exit_code=result.returncode,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))))
                assert result.returncode==0,name
                rows=[json.loads(s) for s in (out/(name+'.log')).read_text().splitlines()];summary=rows.pop()
                assert summary['complete'] and len(rows)==100 and [(r['index'],r['group'],r['engine_seed']) for r in rows]==[(c['index'],c['group'],c['engine_seed']) for c in cases]
                def counts(data):return dict(episodes=len(data),goals=sum(r['controlled_score_delta']>0 for r in data),completed_pass=sum(r['completed_passes']>0 for r in data),joint=sum(r['controlled_score_delta']>0 and r['completed_passes']>0 for r in data))
                report['results'].append(dict(seed=seed,mode=label,overall=counts(rows),groups=[counts([r for r in rows if r['group']==g]) for g in range(5)]))
                write(out/'progress.json',report)
        report.update(passed=True,scope='Diagnostic execution completed. Rates,including failures,are descriptive and do not replace the main confirmation.')
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint()
        if report['source_after']!=before or any(sha(Path(p))!=h for p,h in frozen.items()):report.update(passed=False,error='Frozen evidence changed')
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','error')}),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
