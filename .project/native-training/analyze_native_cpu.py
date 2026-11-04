"""Archive native worker sampling and verify its numerical workload prefix."""
import argparse
import json
from pathlib import Path
import subprocess
import validate

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    args=parser.parse_args(); run=args.run.resolve()
    report=json.loads((run/'report.json').read_text())
    profiles=json.loads((run/'native-profiles.json').read_text())
    current=validate.source_fingerprint()
    assert report['passed'] and report['source_before']==report['source_after']==current
    assert report['artifacts']==report['artifacts_after']
    assert report['environment_before']==report['environment_after']
    assert report['tooling']==report['tooling_after']
    assert report['workers_reaped'] and report['exit_codes']==[0]*4
    assert report['parent_before']['fds']==report['parent_after_close']['fds']
    for artifact,digest in report['artifacts'].items(): assert validate.sha(Path(artifact))==digest
    for name in ('iterations.jsonl','resources.jsonl'):
        assert validate.sha(run/name)==report[name+'_sha256']
    reference=json.loads((args.reference/'report.json').read_text())
    assert reference['passed'] and reference['source_before']==current
    expected=[json.loads(x) for x in (args.reference/'iterations.jsonl').read_text().splitlines()]
    actual=[json.loads(x) for x in (run/'iterations.jsonl').read_text().splitlines()]
    assert len(actual)==report['updates'] and len(expected)>=len(actual)
    for left,right in zip(actual,expected):
        assert (left['version'],left['transitions'],left['update'])==(right['version'],right['transitions'],right['update'])
    experiments=list(profiles['profiles'].values())
    command=['/usr/sbin/gprofng','display','text','-limit','100','-functions',*experiments]
    result=subprocess.run(command,capture_output=True,text=True,check=True,timeout=120)
    (run/'functions.txt').write_text(result.stdout+result.stderr)
    rows=[]
    for line in result.stdout.splitlines():
        fields=line.split(None,4)
        if len(fields)!=5: continue
        try: values=list(map(float,fields[:4]))
        except ValueError: continue
        rows.append(dict(self_cpu_seconds=values[0],self_percent=values[1],
                         inclusive_cpu_seconds=values[2],inclusive_percent=values[3],function=fields[4]))
    assert rows and rows[0]['function']=='<Total>' and rows[0]['self_cpu_seconds']>0
    summary=dict(passed=True,source_sha256=current['sha256'],updates=len(actual),
        numerical_prefix_equal=True,profile=profiles,functions=rows,
        receipts={str(p):validate.sha(p) for p in (run/'report.json',run/'native-profiles.json',run/'functions.txt',args.reference/'report.json')},
        command=command,scope='CPU samples across actual four worker lifetimes, including imports/reset/warmup/step/close. Not phase-exclusive or end-to-end speed evidence. Inclusive rows overlap.',
        raw_profile_hashes={str(p):validate.sha(p) for experiment in experiments for p in sorted(Path(experiment).rglob('*')) if p.is_file()},
        runner_sha256=validate.sha(Path(__file__)))
    (run/'native-analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
    (run/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,updates=len(actual),sampled_cpu_seconds=rows[0]['self_cpu_seconds'])))
    return 0
if __name__=='__main__': raise SystemExit(main())
