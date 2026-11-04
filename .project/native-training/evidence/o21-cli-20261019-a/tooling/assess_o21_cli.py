"""Current-source official CLI parity, process resume and bounded cost assessment."""
import argparse
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time

import quality
from validate import ROOT,sha,source_fingerprint
from validate_learning import SEEDS


def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('build','quality','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    accepted=quality.verify(args.quality/'report.json');before=source_fingerprint()
    reference=ROOT/'.project/native-training/evidence/two-on-one-inference-20261019-a/assessment'
    protocol=read(reference/'protocol.json');exports=Path('/root/work_space/football-artifacts/o21-policy-exports-20261019-a')
    export_report=read(exports/'report.json');assert export_report['passed'] and export_report['source']==protocol['source']
    binary=args.build/'bin/native_ppo_train';core=args.build/'libfootball_engine.so'
    files=[Path(__file__),binary,core,args.quality/'report.json',reference/'cases.txt',exports/'report.json',*[exports/f'{seed}.fpol' for seed in SEEDS]]
    frozen={str(p.resolve()):sha(p) for p in files}
    write(out/'protocol.json',dict(source=before,quality=accepted,build=str(args.build.resolve()),frozen=frozen,
        exports=str(exports),reference=str(reference),modes=['balanced','argmax','sample'],seeds=list(SEEDS),
        gates='All1000 primary and2000 baseline episode JSON lines byte-identical to O20; five new-process resumes match; strict old FPPO rejection',
        benchmark='15 complete CLI invocations,200 matched cases each. monotonic wall and wait4 per-child user,system,maxRSS; different policy trajectories are not an isolated adapter speedup.'))
    env=dict(os.environ,LD_LIBRARY_PATH=str(args.build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    commands=[];reports=[]
    result=dict(passed=False,source_before=before,commands=commands,seeds=reports,protocol_sha256=sha(out/'protocol.json'))
    def run(name,argv,success=True):
        print(name,flush=True);start=time.monotonic()
        with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as error:
            child=subprocess.Popen(list(map(str,argv)),cwd=out,env=env,stdout=stream,stderr=error)
            while True:
                pid,status,usage=os.wait4(child.pid,os.WNOHANG)
                if pid:break
                if time.monotonic()-start>1800:
                    child.kill();pid,status,usage=os.wait4(child.pid,0);break
                time.sleep(.1)
            child.returncode=os.waitstatus_to_exitcode(status)
        elapsed=time.monotonic()-start
        (out/(name+'.time')).write_text(f'{elapsed} {usage.ru_utime} {usage.ru_stime} {usage.ru_maxrss}\n')
        row=dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,wall_seconds=elapsed,
            stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr')))
        commands.append(row)
        if success:assert child.returncode==0,(name,(out/(name+'.stderr')).read_text())
        else:assert child.returncode!=0,name
        return row
    def invocation(seed,mode,cases):return [binary,'--inference-mode',mode,'--policy',exports/f'{seed}.fpol','--inference-cases',cases]
    def episodes(path):
        rows=path.read_bytes().splitlines(keepends=True);summary=json.loads(rows.pop());return rows,summary
    try:
        cases=reference/'cases.txt';shutil.copyfile(cases,out/'cases.txt')
        for seed in SEEDS:
            metadata=next(m for m in export_report['models'] if m['seed']==seed)
            assert metadata['policy_sha256']==sha(exports/f'{seed}.fpol') and metadata['checkpoint_sha256']==protocol['models'][str(seed)]['sha256']
            row=dict(seed=seed,modes={})
            for mode in ('balanced','argmax','sample'):
                name=f'{seed}-{mode}';run(name,invocation(seed,mode,cases))
                rows,summary=episodes(out/(name+'.log'));expected,_=episodes(reference/(name+'.log'))
                assert len(rows)==len(expected)==200 and rows==expected and summary['complete']
                timing=list(map(float,(out/(name+'.time')).read_text().split()))
                row['modes'][mode]=dict(episodes=200,bytes_equal=True,decisions=summary['decisions'],
                    cli_wall_seconds=timing[0],cpu_seconds=timing[1]+timing[2],maximum_rss_kib=int(timing[3]),
                    decision_tps=summary['decisions']/timing[0],engine_wall_seconds=summary['wall_seconds'])
            # One fixed case for each geometry family, across the five models.
            one=out/f'{seed}-resume-case.txt';case=cases.read_text().splitlines()[40*len(reports)]
            one.write_text('0 '+case.split(' ',1)[1]+'\n')
            common=invocation(seed,'balanced',one);state=out/f'{seed}.fifs'
            run(f'{seed}-resume-full',common)
            run(f'{seed}-resume-prefix',[*common,'--inference-decisions',8,'--inference-state-out',state])
            assert state.exists()
            run(f'{seed}-resume-continuation',[*common,'--inference-state-in',state])
            full,full_summary=episodes(out/f'{seed}-resume-full.log')
            prefix,prefix_summary=episodes(out/f'{seed}-resume-prefix.log')
            tail,tail_summary=episodes(out/f'{seed}-resume-continuation.log')
            assert full==prefix+tail and not prefix_summary['complete'] and tail_summary['complete']
            row['new_process_resume_bytes_equal']=True;reports.append(row);write(out/'progress.json',result)
        checkpoint=protocol['models']['42']['path']
        run('strict-old-fppo-rejected',[binary,'--scenario','2v1','--seed',42,'--hidden',64,'--epochs',4,'--minibatch',64,'--updates',0,'--eval-episodes',0,'--load',checkpoint],False)
        assert 'compatib' in (out/'strict-old-fppo-rejected.stderr').read_text().lower()
        result.update(passed=True,primary_episodes=1000,baseline_episodes=2000,new_process_resumes=5,
            strict_old_fppo_rejected=True,quality=accepted)
    except BaseException as error:result['error']=f'{type(error).__name__}: {error}'
    finally:
        result['source_after']=source_fingerprint()
        if before!=result['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()):result.update(passed=False,error='Frozen inputs changed')
        write(out/'report.json',result)
    print(json.dumps({k:result.get(k) for k in ('passed','primary_episodes','new_process_resumes','error')}),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
