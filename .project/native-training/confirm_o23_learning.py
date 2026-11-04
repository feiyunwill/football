"""Register fresh confirmation only after independently audited O23 validation."""
import argparse,hashlib,json,math,os,random,shlex,shutil,struct,subprocess,sys
from pathlib import Path
import numpy as np
import quality
from validate import ROOT,sha,source_fingerprint,runtime_identity
from validate_learning import SEEDS,paired_interval

GROUPS=('interpolation','deeper_attack','wide_attack','close_defender','varied_support')
MASK=(1<<64)-1
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]
def physical(c,scale):
    ax,ay=map(f32,c['attacker']);tx,ty=map(f32,c['teammate']);dx,dy=map(f32,c['defender'])
    return (ax,f32(ay*scale),tx,f32(ty*scale),dx,f32(dy*scale),f32(ax+f32(.02)),ay)
def engine_seeds(data):
    if isinstance(data,dict):
        value=data.get('engine_seed')
        if isinstance(value,int) and 0<=value<=2000000000:yield value
        for v in data.values():yield from engine_seeds(v)
    elif isinstance(data,list):
        for v in data:yield from engine_seeds(v)

def prepare(args):
    study=read(args.study/'report.json');audit=read(args.audit/'report.json');training=read(args.study/'protocol.json')
    assert study['passed'] and study['validation_passed'] and study['selected']=='broad80'
    assert audit['passed'] and audit['validation_passed'] and audit['report_sha256']==sha(args.study/'report.json')
    assert audit['protocol_sha256']==sha(args.study/'protocol.json')
    before=source_fingerprint();assert before==study['source_before']==study['source_after']==training['source']
    quality.verify(args.quality/'report.json')
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    build=args.build.resolve();here=Path(__file__).parent;excluder=here/'exclude_legacy_episode_seeds.cpp'
    files=[Path(__file__),excluder,here/'validate_learning.py',args.study/'report.json',args.audit/'report.json',args.quality/'report.json',build/'bin/native_ppo_train',build/'libfootball_engine.so']
    initial={str(p.resolve()):sha(p) for p in files}
    commands=[]
    def command(name,argv):
        print(name,flush=True)
        with (out/(name+'.log')).open('w') as stream:
            r=subprocess.run(list(map(str,argv)),cwd=build,env=dict(os.environ,LD_LIBRARY_PATH=str(build)),stdout=stream,stderr=subprocess.STDOUT,check=False,timeout=180)
        commands.append(dict(name=name,exit_code=r.returncode,sha256=sha(out/(name+'.log'))));assert r.returncode==0,name
    flags={}
    for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
        if ' = ' in line:k,v=line.split(' = ',1);flags[k]=shlex.split(v)
    link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
    command('compile-exclusions',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',excluder,'-o',out/'exclude.o'])
    index=[i for i,x in enumerate(link) if x.endswith('native_ppo_train.cpp.o')];assert len(index)==1
    link[index[0]]=str(out/'exclude.o');link[link.index('-o')+1]=str(out/'exclude');command('link-exclusions',link)
    corpus=out/'legacy-prefix-seeds.u32le';command('legacy-prefix-exclusions',[out/'exclude',corpus])
    # Loading the seed-only helper still links the accepted native core. Set its
    # search path in the subprocess environment,without changing host settings.
    legacy=np.fromfile(corpus,dtype='<u4');assert legacy.size==5*524289
    forbidden=[];geometries=set();history=[];scale=None
    for model in study['models']:
        p=args.study/f"starts-{model['configuration']}-{model['seed']}.log"
        assert sha(p)==model['starts_sha256'];history.append(dict(path=str(p.resolve()),sha256=sha(p)))
        for line in p.read_text().splitlines():
            row=json.loads(line);forbidden.append(row['engine_seed']);geometries.add(tuple(row['geometry']+row['ball']))
            if scale is None:scale=row['formation_y_scale']
            assert row['formation_y_scale']==scale
    assert scale is not None and scale<0
    evidence=ROOT/'.project/native-training/evidence'
    for p in evidence.rglob('cases.json'):
        rows=read(p)
        if not isinstance(rows,list):continue
        history.append(dict(path=str(p.resolve()),sha256=sha(p)))
        for c in rows:
            if isinstance(c,dict) and all(k in c for k in ('attacker','teammate','defender','engine_seed')):
                geometries.add(physical(c,scale));forbidden.append(c['engine_seed'])
    for p in evidence.glob('two-on-one*/test-2v1-*.log'):
        history.append(dict(path=str(p.resolve()),sha256=sha(p)));forbidden.extend(engine_seeds(read(p)))
    excluded=np.unique(np.concatenate((legacy,np.asarray(forbidden,dtype=np.uint32))))
    excluded.astype('<u4').tofile(out/'forbidden-engine-seeds.u32le')
    def used(seed):
        i=np.searchsorted(excluded,seed);return i<excluded.size and int(excluded[i])==seed
    rng=random.Random(20261020024);cases=[];seen_seeds=set()
    for group in range(5):
        while sum(c['group']==group for c in cases)<40:
            ax=rng.uniform(.44,.68);ay=rng.uniform(-.22,.22);gap=rng.uniform(.12,.20)
            if group==1:ax=rng.uniform(.28,.44)
            if group==2:ay=rng.choice((-1,1))*rng.uniform(.22,.34)
            if group==3:gap=rng.uniform(.06,.12)
            tx=ax+rng.uniform(.08,.18);ty=(-1 if ay>0 else 1)*rng.uniform(.12,.26)
            if group==4:
                tx=ax+rng.uniform(.025,.21);ty=rng.uniform(-.32,.32)
                if abs(ty-ay)<.08:ty=-.24 if ay>=0 else .24
            values=[round(v,6) for v in (ax,ay,tx,ty,ax+gap,ay*.25+rng.uniform(-.06,.06))]
            # Conservatively exclude all seven historical finite-grid partitions.
            if any(abs(values[0]-(.44+.06*i+.0125*p))<=1e-5 and abs(values[1]-(-.16+.16*j+.0125*p))<=1e-5 for p in range(7) for i in range(4) for j in range(3)):continue
            c=dict(index=len(cases),group=group,group_name=GROUPS[group],attacker=values[:2],teammate=values[2:4],defender=values[4:])
            geometry=physical(c,scale)
            if geometry in geometries:continue
            seed=rng.randrange(1,2000000001)
            while used(seed) or seed in seen_seeds:seed=rng.randrange(1,2000000001)
            c.update(engine_seed=seed,action_seed=(20261020024^0x13198A2E03707344^(len(cases)*0x9E3779B97F4A7C15))&MASK)
            geometries.add(geometry);seen_seeds.add(seed);cases.append(c)
    write(out/'cases.json',cases)
    (out/'cases.txt').write_text(''.join(' '.join(map(str,[c['index'],c['group'],0,c['engine_seed'],c['action_seed'],*c['attacker'],*c['teammate'],*c['defender']]))+'\n' for c in cases))
    model_dir=out/'models';model_dir.mkdir();models={}
    old=evidence/'o21-cli-20261019-a/exports';old_export=read(old/'report.json')
    files+=[old/'report.json']
    for seed in SEEDS:
        candidate=next(m for m in study['models'] if m['configuration']=='broad80' and m['seed']==seed)
        p=Path(candidate['policy']);assert sha(p)==candidate['policy_sha256']
        old_p=old/f'{seed}.fpol';old_meta=next(m for m in old_export['models'] if m['seed']==seed)
        assert sha(old_p)==old_meta['policy_sha256']
        models[str(seed)]={}
        for label,source in (('candidate',p),('old_balanced',old_p)):
            target=model_dir/f'{label}-{seed}.fpol';shutil.copyfile(source,target)
            models[str(seed)][label]=dict(path=str(target),sha256=sha(target))
    files+=[out/'cases.json',out/'cases.txt',out/'forbidden-engine-seeds.u32le',out/'legacy-prefix-seeds.u32le']
    files+=[Path(m['path']) for row in models.values() for m in row.values()]
    assert all(sha(Path(p))==h for p,h in initial.items()) and source_fingerprint()==before
    protocol=dict(source=before,environment=runtime_identity(sys.executable),study_report_sha256=sha(args.study/'report.json'),
        audit_sha256=sha(args.audit/'report.json'),build=str(build),quality=str((args.quality/'report.json').resolve()),models=models,
        frozen={str(p.resolve()):sha(p) for p in files},history=history,history_scope='Recorded case JSON arrays,recorded two-on-one*/test-2v1 logs,current study reconstructed training starts; five legacy RNG prefixes conservatively excluded',
        legacy_rng_values=5*524289,unique_forbidden_seeds=int(excluded.size),formation_y_scale=scale,
        geometry_exclusion='Engine FormationEntry coordinates plus ball; legacy finite partitions also excluded with1e-5 tolerance',
        generation_seed=20261020024,groups=list(GROUPS),cases_per_group=40,primary_episodes=1000,
        modes=['candidate','old_balanced','candidate_sample','uniform_random','builtin_ai'],
        gates=dict(success_count_min=930,every_seed_success_count_min=170,every_group_success_count_min=170,
            every_seed_pass_count_min=40,every_seed_joint_count_min=40,paired_old_improvement_ci_low_gt=0),
        bootstrap='10000 crossed paired model/scenario draws,RNG20261015',
        scope='One frozen broad80 candidate,one fresh200-case registration. No selecting or retuning after confirmation.')
    write(out/'protocol.json',protocol);write(out/'preparation-commands.json',commands)
    print(json.dumps(dict(prepared=True,protocol_sha256=sha(out/'protocol.json'),excluded_seeds=int(excluded.size))),flush=True)

def run(args):
    out=args.output.resolve();p=read(out/'protocol.json');assert not (out/'report.json').exists()
    def unchanged():
        assert source_fingerprint()==p['source'] and runtime_identity(sys.executable)==p['environment']
        assert all(sha(Path(path))==h for path,h in p['frozen'].items())
        assert all(sha(Path(row['path']))==row['sha256'] for row in p['history'])
    unchanged();quality.verify(Path(p['quality']));build=Path(p['build']);binary=build/'bin/native_ppo_train'
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    report=dict(passed=False,confirmation_passed=False,protocol_sha256=sha(out/'protocol.json'),commands=[],seeds=[]);primary=[];baseline=[]
    cases=read(out/'cases.json')
    try:
        for seed in SEEDS:
            data={}
            for label in p['modes']:
                mode='sample' if label=='candidate_sample' else ('balanced' if label in ('candidate','old_balanced') else label)
                model=p['models'][str(seed)]['old_balanced' if label=='old_balanced' else 'candidate']['path']
                name=f'{seed}-{label}';print(name,flush=True)
                with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors:
                    result=subprocess.run([str(binary),'--inference-mode',mode,'--policy',model,'--inference-cases',str(out/'cases.txt')],cwd=build,env=env,stdout=stream,stderr=errors,timeout=300)
                report['commands'].append(dict(name=name,exit_code=result.returncode,sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))));assert result.returncode==0,name
                rows=[json.loads(line) for line in (out/(name+'.log')).read_text().splitlines()];summary=rows.pop();assert summary['complete'] and len(rows)==200
                for r,c in zip(rows,cases):
                    assert (r['index'],r['group'],r['engine_seed'])==(c['index'],c['group'],c['engine_seed'])
                    assert r['terminated']^r['truncated'] and 0<=r['completed_passes']<=r['pass_requests']<=r['steps']<=256
                    assert math.isfinite(r['reward']) and math.isfinite(r['controlled_score_delta'])
                data[label]=rows
            rates={label:sum(r['controlled_score_delta']>0 for r in rows) for label,rows in data.items()}
            row=dict(seed=seed,success_counts=rates,pass_count=sum(r['completed_passes']>0 for r in data['candidate']),
                joint_count=sum(r['completed_passes']>0 and r['controlled_score_delta']>0 for r in data['candidate']),
                group_success_counts=[sum(r['controlled_score_delta']>0 for r in data['candidate'] if r['group']==g) for g in range(5)])
            report['seeds'].append(row);primary.append([int(r['controlled_score_delta']>0) for r in data['candidate']]);baseline.append([int(r['controlled_score_delta']>0) for r in data['old_balanced']])
            write(out/'progress.json',report)
        counts={label:sum(r['success_counts'][label] for r in report['seeds']) for label in p['modes']}
        groups=[sum(r['group_success_counts'][g] for r in report['seeds']) for g in range(5)];interval=paired_interval(primary,baseline)
        gates=dict(mean=counts['candidate']>=930,every_seed=all(r['success_counts']['candidate']>=170 for r in report['seeds']),
            groups=all(n>=170 for n in groups),cooperation=all(r['pass_count']>=40 and r['joint_count']>=40 for r in report['seeds']),paired_improvement=interval['low']>0)
        report.update(passed=True,confirmation_passed=all(gates.values()),gates=gates,means={k:n/1000 for k,n in counts.items()},group_means=[n/200 for n in groups],versus_old=interval)
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        try:unchanged()
        except BaseException as error:report.update(passed=False,confirmation_passed=False,error='Frozen inputs changed: '+str(error))
        report['source_after']=source_fingerprint();write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','confirmation_passed','means','gates','error')}),flush=True)
    return 0 if report['passed'] else 1

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','run'))
    parser.add_argument('--output',type=Path,required=True)
    for name in ('study','audit','quality','build'):parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.action=='prepare':
        if any(getattr(args,n) is None for n in ('study','audit','quality','build')):parser.error('prepare requires study,audit,quality,build')
        prepare(args);return 0
    return run(args)
if __name__=='__main__':raise SystemExit(main())
