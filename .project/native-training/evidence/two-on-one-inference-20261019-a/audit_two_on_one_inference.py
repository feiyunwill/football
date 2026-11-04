"""Independently reconstruct frozen confirmation gates from raw episodes."""
import argparse
import json
from pathlib import Path
from validate import ROOT, sha, source_fingerprint
from validate_learning import SEEDS, paired_interval


def read(p): return json.loads(p.read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assessment',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); root=args.assessment; out=args.output
    out.mkdir(parents=True,exist_ok=False)
    p=read(root/'protocol.json'); r=read(root/'report.json'); cases=read(root/'cases.json')
    assert r['passed'] and r['protocol_sha256']==sha(root/'protocol.json')
    assert p['source']==r['source_after']==source_fingerprint()
    assert all(sha(Path(path))==h for path,h in p['frozen'].items())
    assert len(cases)==len({tuple(c['attacker']+c['teammate']+c['defender']) for c in cases})==len({c['engine_seed'] for c in cases})==200
    assert all(sum(c['group']==g for c in cases)==40 for g in range(5))
    old=read(ROOT/'.project/native-training/evidence/two-on-one-broad-20261018-a/assessment/cases.json')
    assert not ({c['engine_seed'] for c in cases}&{c['engine_seed'] for c in old})
    assert not ({tuple(c['attacker']+c['teammate']+c['defender']) for c in cases}&{tuple(c['attacker']+c['teammate']+c['defender']) for c in old})
    validation=read(Path('/tmp/football-inference-validation-20261019-c/report.json'))
    eligible=[m for m in ('balanced','repeat8') if validation['candidates'][m]['eligible']]
    assert p['selected']==max(eligible,key=lambda m:validation['candidates'][m]['mean'])
    commands={c['name']:c for c in r['commands']}; assert len(commands)==25
    selected=p['selected']; seeds=[]; primary=[]; baseline=[]; hashes={}; restores=0
    for seed in SEEDS:
        data={}
        for mode in p['modes']:
            name=f'{seed}-{mode}'; path=root/(name+'.log'); command=commands[name]
            assert command['exit_code']==0 and sha(path)==command['sha256']
            hashes[path.name]=sha(path)
            rows=[json.loads(line) for line in path.read_text().splitlines()]; summary=rows.pop()
            assert summary==dict(summary=True,isolated=True,episodes=200,version=2048,transitions=524288)
            assert len(rows)==200
            for c,e in zip(cases,rows):
                assert (e['index'],e['group'],e['engine_seed'])==(c['index'],c['group'],c['engine_seed'])
                assert e['terminated']^e['truncated'] and 0<=e['completed_passes']<=e['pass_requests']<=e['steps']<=256
                assert abs(e['start_x']-c['attacker'][0]-.02)<1e-6 and abs(e['start_y']-c['attacker'][1])<1e-6
            data[mode]=rows
        rates={m:sum(e['controlled_score_delta']>0 for e in rows)/200 for m,rows in data.items()}
        row=dict(seed=seed,rates=rates,cooperation=sum(e['completed_passes']>0 for e in data[selected])/200,
            joint=sum(e['completed_passes']>0 and e['controlled_score_delta']>0 for e in data[selected])/200)
        assert row==r['seeds'][len(seeds)]; seeds.append(row)
        restores+=sum(e['index']%40==0 and e['steps']>8 for e in data[selected])
        primary.append([int(e['controlled_score_delta']>0) for e in data[selected]])
        baseline.append([int(e['controlled_score_delta']>0) for e in data['argmax']])
    means={m:sum(s['rates'][m] for s in seeds)/5 for m in p['modes']}
    interval=paired_interval(primary,baseline)
    gates=dict(mean=means[selected]>=.8,every_seed=all(s['rates'][selected]>=.65 for s in seeds),
        every_seed_vs_argmax=all(s['rates'][selected]>=s['rates']['argmax']-.05 for s in seeds),
        paired_improvement=interval['low']>0,versus_sample=means[selected]>=means['sample']-.05,
        cooperation=all(s['cooperation']>=.1 and s['joint']>=.1 for s in seeds))
    assert means==r['means'] and interval==r['versus_argmax'] and all(gates.values())==r['confirmation_passed']
    report=dict(passed=True,confirmation_passed=all(gates.values()),gates=gates,means=means,seeds=seeds,
        versus_argmax=interval,report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),
        raw_hashes=hashes,serialized_native_controller_checks=restores,
        source_sha256=p['source']['sha256'],auditor_sha256=sha(Path(__file__)))
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
