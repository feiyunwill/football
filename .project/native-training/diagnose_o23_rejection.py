"""Paired frozen-model inference ablation on old validation cases only."""
import argparse,json,os,subprocess
from pathlib import Path
from validate import ROOT,sha,source_fingerprint

def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def counts(rows):
    failures=[r for r in rows if r['controlled_score_delta']<=0]
    return dict(episodes=len(rows),goals=len(rows)-len(failures),passes=sum(r['completed_passes']>0 for r in rows),
        joint=sum(r['completed_passes']>0 and r['controlled_score_delta']>0 for r in rows),
        failures_without_pass_request=sum(r['pass_requests']==0 for r in failures),
        failures_request_without_completion=sum(r['pass_requests']>0 and r['completed_passes']==0 for r in failures),
        failures_after_completed_pass=sum(r['completed_passes']>0 for r in failures),
        truncations=sum(r['truncated'] for r in rows),turnovers=sum(r['turnovers']>0 for r in rows))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('study','audit','build','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();study=read(args.study/'report.json');audit=read(args.audit/'report.json');sp=read(args.study/'protocol.json')
    assert study['passed'] and not study['validation_passed'] and audit['passed'] and not audit['validation_passed']
    assert audit['report_sha256']==sha(args.study/'report.json') and not study['confirmation_opened']
    before=source_fingerprint();assert before==study['source_after']
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    build=args.build.resolve();binary=build/'bin/native_ppo_train';cases=args.study/'cases.txt'
    assert sp['frozen'][str(binary)]==sha(binary) and sp['frozen'][str(build/'libfootball_engine.so')]==sha(build/'libfootball_engine.so')
    files=[Path(__file__),args.study/'report.json',args.audit/'report.json',cases,binary,build/'libfootball_engine.so']
    files.extend(Path(m['policy']) for m in study['models'])
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,frozen=frozen,modes=['sample','argmax'],models=10,cases_per_model=200,
        evaluations=20,wall_cap_per_evaluation=300,
        scope='Old validation only. Paired inference intervention,not new learning or independent confirmation. No per-seed strategy selection.')
    write(out/'protocol.json',protocol);report=dict(passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=[],results=[])
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    try:
        for model in study['models']:
            label,seed=model['configuration'],model['seed'];assert sha(Path(model['policy']))==model['policy_sha256']
            for mode in ('balanced','sample','argmax'):
                name=f'{label}-{seed}-{mode}'
                if mode=='balanced':path=args.study/f'validation-{label}-{seed}.log'
                else:
                    print(name,flush=True);path=out/(name+'.log');error=out/(name+'.stderr')
                    argv=list(map(str,[binary,'--inference-mode',mode,'--policy',model['policy'],'--inference-cases',cases]))
                    with path.open('w') as stream,error.open('w') as errors:r=subprocess.run(argv,cwd=out,env=env,stdout=stream,stderr=errors,timeout=300)
                    report['commands'].append(dict(name=name,argv=argv,exit_code=r.returncode,stdout_sha256=sha(path),stderr_sha256=sha(error)));assert r.returncode==0,name
                rows=[json.loads(s) for s in path.read_text().splitlines()];summary=rows.pop();assert summary['complete'] and len(rows)==200
                report['results'].append(dict(configuration=label,seed=seed,mode=mode,overall=counts(rows),groups=[counts([r for r in rows if r['group']==g]) for g in range(5)],raw_path=str(path),raw_sha256=sha(path)))
                write(out/'progress.json',report)
        report['passed']=True
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint()
        if before!=report['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()):report.update(passed=False,error='Frozen source or evidence changed')
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','error')}),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
