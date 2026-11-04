"""Join current quality, learning, quiet-duration and installed-model receipts."""
import argparse
import json
from pathlib import Path
import re

import numpy as np
import quality
from validate import ROOT, sha, source_fingerprint


def read(path):return json.loads(path.read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('quality','learning','baseline','delivery','models','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    current=source_fingerprint();verified=quality.verify(args.quality)
    learning=read(args.learning);baseline=read(args.baseline/'report.json')
    delivery=read(args.delivery);models=read(args.models/'report.json')
    assert learning['passed'] and learning['learning_passed']
    assert learning['source_sha256']==current['sha256']
    assert len(learning['tasks'])==1 and '2v1' in learning['tasks']
    assert all(t['learning_passed'] and len(t['seeds'])==5 for t in learning['tasks'].values())
    assert all(row['cooperation']>=.1 and row['cooperative_success']>=.1 for row in learning['tasks']['2v1']['seeds'])
    assert baseline['passed'] and baseline['environment_passed'] and baseline['process_reaped'] and baseline['process_exit']==0
    protocol=read(args.baseline/'protocol.json')
    assert protocol['source_sha256']==current['sha256'] and protocol['minimum_seconds']==1800 and not protocol['smoke_only']
    assert protocol['maximum_steady_rss_growth_bytes']==32*1024*1024 and protocol['maximum_fd_range']==4
    assert protocol['study_report_sha256']==learning['report_sha256'] and protocol['selected']==learning['tasks']['2v1']['selected']
    assert baseline['source_before']==baseline['source_after']==current
    for name,digest in protocol['tooling'].items():assert sha(args.baseline/name)==digest
    for file in ('preflight.json','host-load.json'):
        host=read(args.baseline/file);rows=host['samples'];total=sum(r['seconds'] for r in rows)
        assert not host['compiler_seen'] and not any(r['foreign_compilers'] for r in rows)
        for name,raw in (('foreign','foreign_cores'),('index','index_cores')):
            mean=sum(r[raw]*r['seconds'] for r in rows)/total
            p95=float(np.percentile([r[raw] for r in rows],95))
            assert mean==host[name+'_mean_cores']<=.25
            assert p95==host[name+'_p95_cores']<=.25
    native=read(args.baseline/'native.json');assert native==baseline['native'] and native['passed']
    assert native['requested_seconds']==1800 and native['duration_seconds']>=1800
    assert native['players']==1 and native['native_agents']==2 and native['hidden']==64 and native['rollout']==256
    assert native['seed']==424242 and native['epochs']==4 and native['minibatch']==64 and native['cadence']==10 and native['episode_limit']==256
    assert native['checkpoint_rewards']==(protocol['selected']=='checkpoints64')
    assert native['transitions']==native['updates']*256 and native['fd_before']==native['fd_after']
    assert native['practice_episodes']==0 and native['cooperative_episodes']>0 and native['priming_transitions']==1024
    rows=[json.loads(line) for line in (args.baseline/'minute.jsonl').read_text().splitlines()]
    assert len(rows)>=30 and rows[-1]['elapsed']==native['duration_seconds'] and rows[-1]['transitions']==native['transitions']
    previous_time=previous_count=0
    for row in rows:
        assert row['elapsed']>previous_time and row['transitions']>previous_count and row['transitions']==row['updates']*256
        assert abs(row['tps']-(row['transitions']-previous_count)/(row['elapsed']-previous_time))<1e-9
        previous_time=row['elapsed'];previous_count=row['transitions']
    memory=dict(first=rows[0]['rss'],last=rows[-1]['rss'],peak=max(r['rss'] for r in rows),steady_growth=rows[-1]['rss']-rows[0]['rss'])
    fds=dict(before=native['fd_before'],after=native['fd_after'],minimum=min(r['fds'] for r in rows),maximum=max(r['fds'] for r in rows))
    minute_tps=dict(zip(('p10','median','p90'),map(float,np.percentile([r['tps'] for r in rows],[10,50,90]))))
    assert baseline['memory']==memory and memory['steady_growth']<=32*1024*1024
    assert baseline['fds']==fds and fds['maximum']-fds['minimum']<=4
    assert baseline['minute_tps']==minute_tps and baseline['frozen_isolated'] and baseline['resumed_bytes_equal']
    assert {c['name'] for c in baseline['commands']}=={'compile','link','linkage','soak','fresh-frozen','fresh-resume'}
    for command in baseline['commands']:
        assert command['exit_code']==0 and sha(args.baseline/(command['name']+'.log'))==command['sha256']
    for name,digest in baseline['checkpoint_files'].items():assert sha(args.baseline/name)==digest
    assert (args.baseline/'cli-resume.fppo').read_bytes()==(args.baseline/'expected-resume.fppo').read_bytes()
    frozen=read(args.baseline/'fresh-frozen.log');resume=read(args.baseline/'fresh-resume.log')
    assert frozen['evaluation']['isolated'] and frozen['state_sha256']==frozen['state_before_evaluation_sha256']==sha(args.baseline/'final.fppo')
    assert resume['version']==native['updates']+1 and resume['state_sha256']==sha(args.baseline/'cli-resume.fppo') and len(resume['iterations'])==1
    assert delivery['passed'] and delivery['source_kind']=='exact_current_worktree_not_committed_HEAD'
    assert delivery['source_before']==delivery['source_after']==current
    names={c['name'] for c in delivery['commands']}
    assert {'export-source','snapshot-inputs-match','snapshot-inputs-after','build-wheel','install-wheel',
            'installed-probe','installed-integration','relocated-native-full','relocated-native-resume','relocated-native-frozen'}<=names
    for command in delivery['commands']:
        assert command['exit_code']==0 and sha(args.delivery.parent/command['log'])==command['sha256']
    integration=(args.delivery.parent/'installed-integration.log').read_text()
    assert '\nOK\n' in integration and 'skipped' not in integration
    assert int(re.search(r'^Ran (\d+) tests',integration,re.MULTILINE)[1])>=77
    package=Path(delivery['native_package']['path'])
    for name,digest in delivery['native_package']['manifest']['files'].items():assert sha(package/name)==digest
    export=next(c for c in delivery['commands'] if c['name']=='export-source')['argv']
    assert sha(Path(export[-2]))==delivery['source_archive_sha256']
    inputs=read(Path(export[-1]))['inputs']
    assert all(sha(ROOT/name)==digest for name,digest in inputs.items())
    assert models['passed'] and models['source_before']==models['source_after']==current
    assert models['delivery_report_sha256']==sha(args.delivery)
    assert models['resumed_models_verified']==5 and models['frozen_episodes_verified']==1000
    manifest=read(package/'study-models/manifest.json')
    assert sha(package/'study-models/manifest.json')==models['models_manifest_sha256']
    assert all(sha(package/'study-models'/name)==digest for name,digest in manifest['files'].items())
    assert sha(package/'reproduce-generalization.sh')==manifest['reproduction_script_sha256']==models['script_sha256']
    for row in models['models']:
        assert row['resumed_bytes_equal'] and sha(Path(row['path']))==row['sha256']
        name=f"{row['task']}-{row['seed']}"
        assert (args.models/(name+'-reference.fppo')).read_bytes()==(args.models/(name+'-delivered.fppo')).read_bytes()
        for batch,digest in enumerate(row['frozen_batches']):assert sha(args.models/f'frozen-{name}-b{batch}.json')==digest
    for command in models['commands']:
        assert command['exit_code']==0 and sha(args.models/(command['name']+'.json'))==command['sha256']
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    paths=[args.quality,args.learning,args.baseline/'report.json',args.baseline/'host-load.json',args.delivery,args.models/'report.json']
    report=dict(passed=True,agreed_next_goal_complete=True,source_sha256=current['sha256'],quality=verified,
                tasks=learning['tasks'],duration=dict(seconds=native['duration_seconds'],updates=native['updates'],
                    transitions=native['transitions'],tps=native['transitions_per_second'],memory=memory,
                    fds=fds,minute_tps=minute_tps,native_process_reaped=True,learned_players=1,native_agents=2),
                wheel=delivery['wheel'],package=str(package),replayed_model_episodes=1000,resumed_models=5,
                receipts={str(path.resolve()):sha(path) for path in paths},auditor_sha256=sha(Path(__file__)),
                scope='Registered2v1 cooperation task, five independent seeds and observed completed-pass gate; actual2v1 learner30-minute observed-low-foreign-load WSL baseline; actual Linux/CPython installed wheel and relocated native model replay. No broader football/platform/product milestone inference.')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,agreed_next_goal_complete=True)))


if __name__=='__main__':main()
