"""Bounded retrospective action-rule diagnosis; no policy selection or training."""
import argparse,json,os,subprocess,time
from pathlib import Path
import psutil
from validate import ROOT,sha,source_fingerprint

def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2)+'\n')
def rows(p):
    r=[json.loads(s) for s in p.read_text().splitlines()];summary=r.pop()
    assert summary['complete'] and len(r)==200
    return r

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('study','study-audit','mean','mean-audit','build','output'):ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args();source=source_fingerprint();out=a.output.resolve()
    assert out!=ROOT and ROOT not in out.parents;out.mkdir(exist_ok=False)
    build=a.build.resolve();binary=build/'bin/native_ppo_train';cases=a.study/'cases.txt'
    inputs=[Path(__file__),binary,build/'libfootball_engine.so',cases];models=[]
    for label,study,audit in [('final8192',a.study,a.study_audit),('mean4',a.mean,a.mean_audit)]:
        r=read(study/'report.json');v=read(audit/'report.json')
        assert r['passed'] and not r['validation_passed'] and v['passed'] and not v['validation_passed']
        assert r['source_after']==source and v['report_sha256']==sha(study/'report.json')
        inputs.extend([study/'report.json',study/'protocol.json',audit/'report.json'])
        for m in r['models']:
            policy=Path(m['policy']);assert sha(policy)==m['policy_sha256']
            log=study/(f'validation-annealed-{m["seed"]}.log' if label=='final8192' else f'validation-{m["seed"]}.log')
            inputs.extend([policy,log]);models.append(dict(label=label,seed=m['seed'],policy=str(policy),balanced=str(log)))
    frozen={str(p.resolve()):sha(p) for p in inputs}
    protocol=dict(source=source,frozen=frozen,models=models,cases=str(cases.resolve()),mode='sample',
        new_episodes=2000,max_command_seconds=300,max_total_seconds=3600,max_rss_bytes=512*1024**2,
        scope='Old validation only. Compare two fixed rejected policies and action rules; no selection, new confirmation, controller changes or training.')
    write(out/'protocol.json',protocol);r=dict(passed=False,source_before=source,protocol_sha256=sha(out/'protocol.json'),commands=[],cells=[])
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    started=time.monotonic()
    try:
        for m in models:
            name=f'sample-{m["label"]}-{m["seed"]}';print(name,flush=True);t=time.monotonic();peak=0
            argv=[str(binary),'--inference-mode','sample','--policy',m['policy'],'--inference-cases',str(cases)]
            with (out/(name+'.log')).open('w') as log,(out/(name+'.stderr')).open('w') as err:
                child=subprocess.Popen(argv,cwd=build,env=env,stdout=log,stderr=err);proc=psutil.Process(child.pid)
                while child.poll() is None:
                    try:peak=max(peak,proc.memory_info().rss)
                    except psutil.NoSuchProcess:pass
                    if peak>512*1024**2 or time.monotonic()-t>300 or time.monotonic()-started>3600:
                        child.kill();child.wait();raise RuntimeError('Diagnostic budget exceeded')
                    time.sleep(.2)
            r['commands'].append(dict(name=name,argv=argv,exit_code=child.returncode,seconds=time.monotonic()-t,peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))))
            assert child.returncode==0
            sample=rows(out/(name+'.log'));balanced=rows(Path(m['balanced']))
            assert [(x['index'],x['group'],x['engine_seed']) for x in sample]==[(x['index'],x['group'],x['engine_seed']) for x in balanced]
            counts=lambda rr:dict(goals=sum(x['controlled_score_delta']>0 for x in rr),passes=sum(x['completed_passes']>0 for x in rr),joint=sum(x['controlled_score_delta']>0 and x['completed_passes']>0 for x in rr),groups=[sum(x['controlled_score_delta']>0 for x in rr if x['group']==g) for g in range(5)])
            r['cells'].append(dict(label=m['label'],seed=m['seed'],sample=counts(sample),balanced=counts(balanced)))
            write(out/'progress.json',r)
        r['passed']=True
    except BaseException as e:r['error']=f'{type(e).__name__}: {e}'
    finally:
        r['source_after']=source_fingerprint()
        if r['source_after']!=source or any(sha(Path(p))!=h for p,h in frozen.items()):r.update(passed=False,error='Frozen source/evidence changed')
        r['seconds']=time.monotonic()-started;write(out/'report.json',r)
    print(json.dumps({k:r.get(k) for k in ('passed','cells','error')}),flush=True)
    return 0 if r['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
