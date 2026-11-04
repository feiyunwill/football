"""Bind selective-digest performance to current source and full quality evidence."""
import json
from pathlib import Path
import statistics
import quality
import validate
from benchmark_selected_digests import interval

def main():
    evidence=Path(__file__).with_name('evidence')
    output=evidence/'selected-digests-audit-20261017-a'
    output.mkdir(exist_ok=False)
    quality_path=evidence/'selected-digests-quality-20261017-a/report.json'
    accepted=quality.verify(quality_path)
    experiment_path=evidence/'selected-digests-20261017-b/report.json'
    experiment=json.loads(experiment_path.read_text())
    current=validate.source_fingerprint()
    assert experiment['passed'] and experiment['source_before']==experiment['source_after']==current
    assert experiment['environment']==validate.runtime_identity(__import__('sys').executable)
    for path,digest in experiment['engine'].items(): assert validate.sha(Path(path))==digest
    for name,digest in experiment['tooling'].items():
        assert validate.sha(Path(__file__).with_name(name))==digest
        assert validate.sha(experiment_path.parent/name)==digest
    pairs=experiment['digest']['pairs']
    ratios=[(r['baseline']['parent_cpu_seconds']+r['baseline']['worker_cpu_seconds'])/
            (r['candidate']['parent_cpu_seconds']+r['candidate']['worker_cpu_seconds']) for r in pairs]
    reduction=1-statistics.median(1/r for r in ratios)
    assert reduction==experiment['digest']['median_cpu_reduction'] and reduction>=.5
    ci=interval(ratios)
    assert ci==experiment['digest']['speedup_ci95'] and ci[0]>1
    assert experiment['collector']['exact_replay'] and experiment['exit_codes']==[0]*4
    for pair in experiment['collector']['pairs']:
        assert pair['baseline']['transitions']==pair['candidate']['transitions']==40
    log=(quality_path.parent/'python-integration.log').read_text()
    assert 'Ran 74 tests in ' in log and '\nOK\n' in log and 'skipped' not in log
    report=dict(passed=True,source=current,quality=accepted,digest_cpu_reduction=reduction,
        speedup_ci95=ci,receipts={str(p.relative_to(evidence)):validate.sha(p) for p in (quality_path,experiment_path)},
        runner_sha256=validate.sha(Path(__file__)),
        limits=['Only digest IPC phase performance accepted; no full training speedup claim',
                'Previous PPO scaling, learning and wheel receipts remain historical; GPU remains deferred'])
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,digest_cpu_reduction=reduction)))
    return 0
if __name__=='__main__': raise SystemExit(main())
