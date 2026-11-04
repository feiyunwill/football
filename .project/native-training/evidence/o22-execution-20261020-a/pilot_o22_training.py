"""Bounded current-source training cost and exact process-resume pilot."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import time
import psutil
import quality
from validate import ROOT,sha,source_fingerprint

def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2)+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('build','quality','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    verified=quality.verify(args.quality/'report.json');before=source_fingerprint();binary=args.build/'bin/native_ppo_train'
    files=[Path(__file__),binary,args.build/'libfootball_engine.so',args.quality/'report.json']
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,frozen=frozen,seed=42,updates=64,rollout=256,hidden=64,epochs=4,minibatch=64,
        total_wall_budget_seconds=1800,phases='initial export; full64; prefix32; resume32; known-case initial/final evaluation',
        scope='Training/resume/cost pilot,not a five-seed learning acceptance; old cases diagnostic only')
    write(out/'protocol.json',protocol)
    common=[binary,'--scenario','2v1','--seed',42,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,
        '--cadence',10,'--episode-limit',256,'--eval-episodes',0,'--no-initial-eval']
    env=dict(os.environ,LD_LIBRARY_PATH=str(args.build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    started=time.monotonic();commands=[];samples=[]
    report=dict(passed=False,source_before=before,quality=verified,protocol_sha256=sha(out/'protocol.json'),commands=commands)
    def run(name,argv):
        print(name,flush=True);start=time.monotonic();peak_rss=peak_fds=0
        with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors:
            child=subprocess.Popen(list(map(str,argv)),cwd=out,env=env,stdout=stream,stderr=errors)
            proc=psutil.Process(child.pid)
            while child.poll() is None:
                if time.monotonic()-started>1800:
                    child.terminate()
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                    raise TimeoutError('Pilot1800-second total wall cap reached')
                try:
                    rss=proc.memory_info().rss;fds=proc.num_fds();cpu=proc.cpu_times()
                    peak_rss=max(peak_rss,rss);peak_fds=max(peak_fds,fds)
                    samples.append(dict(command=name,seconds=time.monotonic()-start,rss=rss,fds=fds,user=cpu.user,system=cpu.system))
                except psutil.NoSuchProcess:pass
                time.sleep(.1)
        row=dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,seconds=time.monotonic()-start,
            peak_rss=peak_rss,peak_fds=peak_fds,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr')))
        commands.append(row);assert child.returncode==0,(name,(out/(name+'.stderr')).read_text())
        return row
    try:
        run('initial',[*common,'--updates',0,'--export-policy',out/'initial.fpol'])
        run('full',[*common,'--updates',64,'--save',out/'full.fppo','--export-policy',out/'full.fpol'])
        run('prefix',[*common,'--updates',32,'--save',out/'prefix.fppo'])
        run('resumed',[*common,'--updates',32,'--load',out/'prefix.fppo','--save',out/'resumed.fppo','--export-policy',out/'resumed.fpol'])
        full=read(out/'full.log');prefix=read(out/'prefix.log');resumed=read(out/'resumed.log')
        assert full['iterations'][:32]==prefix['iterations'] and full['iterations'][32:]==resumed['iterations']
        assert (out/'full.fppo').read_bytes()==(out/'resumed.fppo').read_bytes()
        assert (out/'full.fpol').read_bytes()==(out/'resumed.fpol').read_bytes()
        assert full['version']==resumed['version']==64 and full['total_transitions']==16384
        assert all(math.isfinite(r[k]) for r in full['iterations'] for k in ('loss','entropy','gradient_norm','parameter_delta'))
        assert all(r['parameter_delta']>0 for r in full['iterations'])
        cases=ROOT/'.project/native-training/evidence/two-on-one-broad-20261018-a/assessment/cases.txt'
        diagnostic={}
        for mode in ('initial','full'):
            run(mode+'-validation',[binary,'--inference-mode','balanced','--policy',out/(mode+'.fpol'),'--inference-cases',cases])
            rows=[json.loads(line) for line in (out/(mode+'-validation.log')).read_text().splitlines()];summary=rows.pop()
            assert summary['complete'] and len(rows)==200
            diagnostic[mode]=dict(success=sum(r['controlled_score_delta']>0 for r in rows)/200,
                cooperation=sum(r['completed_passes']>0 for r in rows)/200,joint=sum(r['controlled_score_delta']>0 and r['completed_passes']>0 for r in rows)/200)
        cost=next(c for c in commands if c['name']=='full')
        report.update(passed=True,resume_bytes_equal=True,policy_export_bytes_equal=True,transitions=16384,
            full_training_process_seconds=cost['seconds'],process_transition_tps=16384/cost['seconds'],
            peak_training_rss=cost['peak_rss'],peak_training_fds=cost['peak_fds'],validation_diagnostic=diagnostic,
            warning='64updates only; measured process cost includes initialization/checkpoints. No full-study learning or duration claim.')
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint()
        if before!=report['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()):report.update(passed=False,error='Frozen inputs changed')
        write(out/'resources.json',samples);report['resource_log_sha256']=sha(out/'resources.json')
        report['total_seconds']=time.monotonic()-started
        report['output_bytes']=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','process_transition_tps','peak_training_rss','validation_diagnostic','error')}),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
