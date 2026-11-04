"""Schema5 retrospective late-update diagnosis; rejected final model; no selection."""
import argparse,json,os,subprocess,time
from pathlib import Path
from validate import ROOT,sha,source_fingerprint
SEEDS=(42,123,2026,31415,271828)
VERSIONS=(7424,7680,7936,8192)
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('study','audit','build','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();study=read(args.study/'report.json');audit=read(args.audit/'report.json')
    assert study['passed'] and not study['validation_passed'] and audit['passed'] and not audit['validation_passed']
    assert audit['report_sha256']==sha(args.study/'report.json')
    before=source_fingerprint();assert before==study['source_after'] and before['sha256']==audit['source_sha256']
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    build=args.build.resolve();binary=build/'bin/native_ppo_train';cases=args.study/'cases.txt'
    checkpoints=[args.study/f'models/annealed-{s}-u{v}.fppo' for s in SEEDS for v in VERSIONS]
    files=[Path(__file__),binary,build/'libfootball_engine.so',cases,args.study/'report.json',args.audit/'report.json',*checkpoints]
    files.extend(args.study/f'validation-annealed-{s}.log' for s in SEEDS)
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,frozen=frozen,seeds=list(SEEDS),versions=list(VERSIONS),
        cases='Original200-case old validation only; no new cases',mode='balanced',updates=0,
        new_evaluations=15,episodes_per_evaluation=200,final8192_reused=True,training_study=str(args.study.resolve()),audit=str(args.audit.resolve()),wall_seconds_per_command=300,
        analysis='Report each seed/version success and joint counts and per-seed max-minus-min rate. No selecting best checkpoints or changing the rejected candidate.',
        scope='Retrospective mechanism diagnosis. Does not establish learning acceptance,causality of optimizer settings,or a new independently confirmed candidate.')
    write(out/'protocol.json',protocol);report=dict(passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=[],cells=[])
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    def run(name,argv):
        print(name,flush=True);started=time.monotonic()
        with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors:r=subprocess.run(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors,timeout=300)
        report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=r.returncode,seconds=time.monotonic()-started,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))));assert r.returncode==0,name
    try:
        for seed in SEEDS:
            for version in VERSIONS:
                if version==8192:path=args.study/f'validation-annealed-{seed}.log'
                else:
                    checkpoint=args.study/f'models/annealed-{seed}-u{version}.fppo';policy=out/f'{seed}-{version}.fpol';name=f'export-{seed}-{version}'
                    run(name,[binary,'--scenario','2v1_broad_annealed','--seed',seed,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,'--cadence',10,'--episode-limit',256,'--no-initial-eval','--eval-episodes',0,'--updates',0,'--load',checkpoint,'--export-policy',policy])
                    exported=read(out/(name+'.log'));assert exported['start_version']==exported['version']==version and exported['total_transitions']==version*256 and not exported['iterations']
                    assert exported['state_before_evaluation_sha256']==exported['state_sha256']==sha(checkpoint)
                    name=f'validation-{seed}-{version}';run(name,[binary,'--inference-mode','balanced','--policy',policy,'--inference-cases',cases]);path=out/(name+'.log')
                rows=[json.loads(line) for line in path.read_text().splitlines()];summary=rows.pop();assert summary['complete'] and len(rows)==200
                report['cells'].append(dict(seed=seed,version=version,goals=sum(r['controlled_score_delta']>0 for r in rows),passes=sum(r['completed_passes']>0 for r in rows),joint=sum(r['controlled_score_delta']>0 and r['completed_passes']>0 for r in rows),raw_path=str(path),raw_sha256=sha(path)))
                write(out/'progress.json',report)
        report['per_seed_spreads']=[dict(seed=s,goal_rate_range=(max(r['goals'] for r in report['cells'] if r['seed']==s)-min(r['goals'] for r in report['cells'] if r['seed']==s))/200) for s in SEEDS]
        report.update(passed=True,scope=protocol['scope'])
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint()
        if before!=report['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()):report.update(passed=False,error='Frozen source or evidence changed')
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','per_seed_spreads','error')}),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
