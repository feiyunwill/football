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
    assert len(learning['tasks'])==2
    assert all(t['learning_passed'] and len(t['seeds'])==5 for t in learning['tasks'].values())
    assert baseline['passed'] and baseline['environment_passed']
    protocol=read(args.baseline/'protocol.json')
    assert protocol['source_sha256']==current['sha256']
    for file in ('preflight.json','host-load.json'):
        host=read(args.baseline/file);rows=host['samples'];total=sum(r['seconds'] for r in rows)
        assert not any(r['foreign_compilers'] for r in rows)
        for name,raw in (('foreign','foreign_cores'),('index','index_cores')):
            mean=sum(r[raw]*r['seconds'] for r in rows)/total
            p95=float(np.percentile([r[raw] for r in rows],95))
            assert mean==host[name+'_mean_cores']<=.25
            assert p95==host[name+'_p95_cores']<=.25
    duration=read(args.baseline/'evidence/report.json')
    analysis=read(args.baseline/'analysis/report.json');frozen=read(args.baseline/'frozen/report.json')
    assert duration['passed'] and analysis['passed'] and frozen['passed']
    assert duration['source_before']==duration['source_after']==current
    assert duration['duration_seconds']>=1800 and duration['workers_reaped']
    assert duration['exit_codes']==[0]*4 and duration['parent_before']['fds']==duration['parent_after_close']['fds']
    for name,digest in analysis['receipts'].items():assert sha(args.baseline/'evidence'/name)==digest
    assert delivery['passed'] and delivery['source_kind']=='exact_current_worktree_not_committed_HEAD'
    assert delivery['source_before']==delivery['source_after']==current
    names={c['name'] for c in delivery['commands']}
    assert {'export-source','snapshot-inputs-match','snapshot-inputs-after','build-wheel','install-wheel',
            'installed-probe','installed-integration','relocated-native-full','relocated-native-resume','relocated-native-frozen'}<=names
    for command in delivery['commands']:
        assert command['exit_code']==0 and sha(args.delivery.parent/command['log'])==command['sha256']
    integration=(args.delivery.parent/'installed-integration.log').read_text()
    assert '\nOK\n' in integration and 'skipped' not in integration
    assert int(re.search(r'^Ran (\d+) tests',integration,re.MULTILINE)[1])>=76
    package=Path(delivery['native_package']['path'])
    for name,digest in delivery['native_package']['manifest']['files'].items():assert sha(package/name)==digest
    export=next(c for c in delivery['commands'] if c['name']=='export-source')['argv']
    assert sha(Path(export[-2]))==delivery['source_archive_sha256']
    inputs=read(Path(export[-1]))['inputs']
    assert all(sha(ROOT/name)==digest for name,digest in inputs.items())
    assert models['passed'] and models['source_before']==models['source_after']==current
    assert models['delivery_report_sha256']==sha(args.delivery)
    assert models['resumed_models_verified']==10 and models['frozen_episodes_verified']==2000
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
                tasks=learning['tasks'],duration=dict(seconds=duration['duration_seconds'],updates=duration['updates'],
                    transitions=duration['transitions'],tps=duration['transitions_per_second'],memory=analysis['memory'],
                    fds=analysis['fds'],minute_tps=analysis['minute_tps'],workers_reaped=True),
                wheel=delivery['wheel'],package=str(package),replayed_model_episodes=2000,resumed_models=10,
                receipts={str(path.resolve()):sha(path) for path in paths},auditor_sha256=sha(Path(__file__)),
                scope='Two registered single-player varied-start shooting tasks and five seeds/task; observed low-foreign-load WSL baseline; actual Linux/CPython installed wheel and relocated native model replay. No broader football/platform/product milestone inference.')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,agreed_next_goal_complete=True)))


if __name__=='__main__':main()
