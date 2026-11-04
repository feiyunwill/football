"""Verify fixed-workload equivalence before reporting an exploratory worker ratio."""
import argparse
import json
from pathlib import Path
import quality
import validate

def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--single',type=Path,required=True)
    parser.add_argument('--four',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); paths=[args.single.resolve(),args.four.resolve()]
    runs=[json.loads((p/'report.json').read_text()) for p in paths]
    current=validate.source_fingerprint(); accepted=quality.verify(Path(__file__).with_name('evidence')/'selected-digests-quality-20261017-a/report.json')
    for path,run in zip(paths,runs):
        assert run['passed'] and run['source_before']==run['source_after']==current
        assert run['environment_before']==run['environment_after']
        assert run['artifacts']==run['artifacts_after'] and run['tooling']==run['tooling_after']
        assert run['workers_reaped'] and run['exit_codes']==[0]*run['protocol']['workers']
        assert run['parent_before']['fds']==run['parent_after_close']['fds']
        for name in ('iterations.jsonl','resources.jsonl'):
            assert validate.sha(path/name)==run[name+'_sha256']
        assert validate.sha(path/'latest-checkpoint.json')==run['checkpoint_sha256']
        for name,digest in run['tooling'].items(): assert validate.sha(path/name)==digest
        for artifact,digest in run['artifacts'].items(): assert validate.sha(Path(artifact))==digest
    one,four=runs
    assert one['protocol']['workers']==1 and four['protocol']['workers']==4
    for key in ('players','cadence','episodes_per_update','horizon','hidden','epochs','minibatch'):
        assert one['protocol'][key]==four['protocol'][key]
    assert one['updates']==four['updates'] and one['transitions']==four['transitions']
    assert one['replay_sha256']==four['replay_sha256']
    compared=0
    with (paths[0]/'iterations.jsonl').open() as a, (paths[1]/'iterations.jsonl').open() as b:
        for left,right in zip(a,b,strict=True):
            x,y=json.loads(left),json.loads(right)
            assert (x['version'],x['transitions'],x['update'])==(y['version'],y['transitions'],y['update'])
            compared+=1
    assert compared==one['updates']
    checkpoints=[json.loads((p/'latest-checkpoint.json').read_text()) for p in paths]
    assert canonical(checkpoints[0]['state'])==canonical(checkpoints[1]['state'])
    ratio=one['duration_seconds']/four['duration_seconds']
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    report=dict(passed=True,source_sha256=current['sha256'],quality=accepted,
        updates=compared,transitions=one['transitions'],replay_sha256=one['replay_sha256'],learner_payload_equal=True,
        single_seconds=one['duration_seconds'],four_seconds=four['duration_seconds'],observed_four_over_single_tps=ratio,
        stage_seconds={name:{k:v/1e9 for k,v in run['stage_totals_ns'].items()} for name,run in zip(('single','four'),runs)},
        cross_run_environment_equal=one['environment_before']==four['environment_before'],
        scope='One historical four-worker run and one subsequent fixed-workload single-worker run; exploratory ratio, no independent repeats or interleaved order',
        all_configuration_twofold_accepted=False,
        receipts={str(p/'report.json'):validate.sha(p/'report.json') for p in paths},
        runner_sha256=validate.sha(Path(__file__)))
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,observed_speedup=ratio,updates=compared)))
    return 0
if __name__=='__main__': raise SystemExit(main())
