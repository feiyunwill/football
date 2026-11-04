"""Verify current quality, paired-update evidence and baseline worker replay parity."""
import hashlib
import json
from pathlib import Path
import statistics
import random
import quality
import validate

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=Path(__file__).with_name('evidence')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(name): return json.loads((EVIDENCE/name/'report.json').read_text())
def main():
    target=EVIDENCE/'ppo-combined-audit-20261015-b'
    target.mkdir(exist_ok=False)
    accepted=quality.verify(EVIDENCE/'ppo-combined-quality-20261015-a/report.json')
    micro=read('ppo-combined-20261015-a'); edges=read('ppo-combined-edges-20261015-a')
    workers=read('ppo-combined-workers-20261015-a'); previous=read('o4-ppo-workers-20261015-a')
    assert micro['passed'] and edges['passed'] and workers['passed'] and previous['passed']
    assert edges['experiment_sha256']==sha(EVIDENCE/'ppo-combined-20261015-a/report.json')
    assert edges['runner_sha256']==sha(Path(__file__).with_name('check_ppo_equivalence.py'))
    for command in workers['commands']:
        assert command['exit_code']==0
        assert command['sha256']==sha(EVIDENCE/'ppo-combined-workers-20261015-a'/(command['name']+'.log'))
    for label,path in [('policy','categorical_policy.cpp'),('math','ppo_math.cpp')]:
        assert micro['artifacts']['candidate-'+label]==sha(ROOT/'engine/src/training'/path)
    for path,digest in micro['inputs'].items(): assert sha(ROOT/path)==digest
    for row in micro['workloads']:
        reduction=1-statistics.median(r['candidate']/r['baseline'] for r in row['pairs'])
        assert reduction==row['median_cpu_reduction'] and reduction>=.10 and row['speedup_ci95'][0]>1
        ratios=[r['baseline']/r['candidate'] for r in row['pairs']]
        rng=random.Random(20261015)
        boot=sorted(statistics.median(rng.choices(ratios,k=len(ratios))) for _ in range(10000))
        assert row['speedup_ci95']==[boot[249],boot[9749]]
    current=validate.source_fingerprint()
    assert workers['source_before']==workers['source_after']==current
    old={(r['players'],r['cadence'],r['workers']):r for r in previous['workloads']}
    comparisons=0
    for row in workers['workloads']:
        baseline=old[(row['players'],row['cadence'],row['workers'])]['samples'][0]
        for sample in row['samples']:
            assert sample['replay']==baseline['replay']
            assert sample['checkpoint_sha256']==row['samples'][0]['checkpoint_sha256']
            comparisons+=1
    assert comparisons==36 and workers['resume_verified']
    # Source and compiled-core identity intentionally change across builds.
    # Compare saved learner payloads; never bypass identity checks during restore.
    snapshots=[json.loads(p.read_text()) for p in (
        Path('/tmp/football-o4-ppo-20261015-a/full.json'),
        Path('/tmp/football-ppo-combined-workers-20261015-a/full.json'))]
    assert snapshots[0]['identity']['source']==previous['source_before']['sha256']
    assert snapshots[1]['identity']['source']==current['sha256']
    payloads=[json.dumps(dict(state=s['state'],next_update=s['next_update']),sort_keys=True).encode() for s in snapshots]
    assert payloads[0]==payloads[1]
    receipts=['ppo-combined-20261015-a','ppo-combined-edges-20261015-a',
              'ppo-combined-quality-20261015-a','ppo-combined-workers-20261015-a','o4-ppo-workers-20261015-a']
    report=dict(passed=True,quality=accepted,source=current,baseline_worker_replays_equal=comparisons,
        cross_process_resume=True,receipts={r:sha(EVIDENCE/r/'report.json') for r in receipts},
        saved_baseline_learner_payload_equal=True,saved_payload_sha256=hashlib.sha256(payloads[0]).hexdigest(),
        tooling={p.name:sha(p) for p in Path(__file__).parent.glob('*.py')},
        note='Microbenchmark predates the added scalar contract test; candidate production and header hashes verified unchanged. Earlier learning/delivery receipts remain historical.',
        limitations=['Isolated update gain does not establish whole-pipeline speedup',
                     'Short worker episodes do not establish sustained training scaling',
                     'Current wheel not rebuilt; remote CI and GPU acceptance remain open'])
    (target/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,baseline_worker_replays_equal=comparisons)))
    return 0
if __name__=='__main__': raise SystemExit(main())
