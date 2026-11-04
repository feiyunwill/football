"""Descriptive decision traces for two previously identified weak argmax models."""
import collections
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess

from validate import ROOT, sha, source_fingerprint


def main():
    work = Path('/tmp/football-inference-traces-20261019-a'); work.mkdir(exist_ok=False)
    build = Path('/tmp/football-native-assessment-20261015')
    previous = ROOT / '.project/native-training/evidence/two-on-one-broad-20261018-a/assessment'
    protocol = json.loads((previous / 'protocol.json').read_text()); before = source_fingerprint()
    assert before == protocol['source']
    source = Path(__file__).with_name('diagnose_two_on_one_inference.cpp')
    for p in (Path(__file__), source): shutil.copyfile(p, work / p.name)
    report = dict(passed=False, diagnostic_only=True, source_before=before, commands=[], results=[],
        case_sha256=sha(previous / 'cases.txt'), evaluator_source_sha256=sha(source), runner_sha256=sha(Path(__file__)))
    (work / 'protocol.json').write_text(json.dumps(dict(seeds=[123,31415],modes=['argmax','sample'],
        cases='Prior broad200 cases; descriptive data only, not a new confirmation',
        before=before,case_sha256=report['case_sha256'],evaluator_source_sha256=sha(source)),indent=2)+'\n')
    env = dict(os.environ,GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),
        GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'),LD_LIBRARY_PATH=str(build))
    def run(name,argv,environment=env):
        print(name,flush=True)
        with (work/(name+'.log')).open('w') as out:
            result=subprocess.run(list(map(str,argv)),cwd=build,env=environment,stdout=out,stderr=subprocess.STDOUT,timeout=600)
        report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=result.returncode,sha256=sha(work/(name+'.log'))))
        assert result.returncode==0,name
    try:
        flags={}
        for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:
                key,value=line.split(' = ',1);flags[key]=shlex.split(value)
        link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
        obj=work/'trace.o';binary=work/'trace'
        run('compile',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',source,'-o',obj])
        indexes=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(indexes)==1
        link[indexes[0]]=str(obj);link[link.index('-o')+1]=str(binary);run('link',link)
        for seed in (123,31415):
            model=Path(protocol['models'][str(seed)]['path']);assert sha(model)==protocol['models'][str(seed)]['sha256']
            for mode in ('argmax','sample'):
                name=f'{seed}-{mode}';trace=work/(name+'.trace.jsonl')
                run(name,[binary,seed,model,mode,previous/'cases.txt'],dict(env,FOOTBALL_INFERENCE_TRACE=str(trace)))
                original=previous/f'{seed}-trained_{mode}.log'
                assert (work/(name+'.log')).read_bytes()==original.read_bytes(),'Tracing perturbed output'
                episodes=[json.loads(line) for line in (work/(name+'.log')).read_text().splitlines()][:-1]
                traces=collections.defaultdict(list)
                for line in trace.read_text().splitlines():
                    row=json.loads(line);traces[row['index']].append(row)
                summaries=[]
                for episode in episodes:
                    rows=traces[episode['index']];assert len(rows)==episode['steps']
                    longest=run_length=stationary=0;previous_action=None;start=0
                    for i,row in enumerate(rows):
                        if row['action']==previous_action:run_length+=1
                        else:run_length=1;start=i
                        previous_action=row['action'];longest=max(longest,run_length)
                        if run_length>=8:
                            first=rows[i-7]
                            if math.hypot(row['ball_x']-first['ball_x'],row['ball_y']-first['ball_y'])<.001:stationary+=1
                    summaries.append(dict(index=episode['index'],success=episode['controlled_score_delta']>0,
                        steps=episode['steps'],truncated=episode['truncated'],longest_repeated_action=longest,
                        stationary_repeated_decisions=stationary,
                        actions=dict(collections.Counter(r['action'] for r in rows))))
                failures=[r for r in summaries if not r['success']]
                report['results'].append(dict(seed=seed,mode=mode,success=sum(r['success'] for r in summaries)/200,
                    episodes=200,failures=len(failures),truncated=sum(r['truncated'] for r in summaries),
                    failures_with_run8=sum(r['longest_repeated_action']>=8 for r in failures),
                    failures_with_run32=sum(r['longest_repeated_action']>=32 for r in failures),
                    failures_with_stationary_run8=sum(r['stationary_repeated_decisions']>0 for r in failures),
                    trace_sha256=sha(trace),parity_exact=True))
                (work/(name+'.episodes.json')).write_text(json.dumps(summaries,indent=2)+'\n')
        report['passed']=True
    finally:
        report['source_after']=source_fingerprint()
        assert report['source_after']==before and report['evaluator_source_sha256']==sha(source) and report['runner_sha256']==sha(Path(__file__))
        (work/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],results=report['results'])),flush=True)


if __name__=='__main__':main()
