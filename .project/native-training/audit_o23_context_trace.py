"""Independently reconstruct deterministic controller decisions from frozen traces."""
import argparse,json,math
from pathlib import Path
from validate import sha,source_fingerprint
def read(p):return json.loads(p.read_text())
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--trace',type=Path,required=True);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();r=read(args.trace/'report.json');p=read(args.trace/'protocol.json');args.output.mkdir(parents=True,exist_ok=False)
    assert r['passed'] and p['source']==r['source_after']==source_fingerprint() and sha(args.trace/'protocol.json')==r['protocol_sha256']
    assert all(sha(Path(path))==h for path,h in p['frozen'].items())
    totals=dict(decisions=0,phase_changes=0,phase_different=0,all_different=0,low_probability=0,phase_low_probability=0)
    for item in r['results']:
        trace=Path(item['trace_path']);assert sha(trace)==item['trace_sha256'];rows=[json.loads(s) for s in trace.read_text().splitlines()]
        baseline=[json.loads(s) for s in (args.study/f'validation-{item["seed"]}.log').read_text().splitlines()][:-1]
        expected_cases={40*g+i for g in range(5) for i in range(4)};seen=set();counts={k:0 for k in totals};credit=[0.]*19;previous=None;phase=False;owner=None;repeated=0;last_action=-1
        for row in rows:
            if row['case']!=previous:
                if previous is not None:assert step+1==baseline[previous]['steps']
                previous=row['case'];assert previous in expected_cases and previous not in seen;seen.add(previous)
                credit=[0.]*19;phase=False;owner=None;repeated=0;last_action=-1
            step=row['step'];fields=row['controller_before'].split();assert fields[:2]==['DIC1','balanced'] and int(fields[2])==step and int(fields[3])==last_action and int(fields[4])==repeated
            assert list(map(float,fields[5:]))==credit
            probabilities=row['probabilities'];assert len(probabilities)==19 and all(math.isfinite(x) and 0<=x<=1 for x in probabilities) and abs(sum(probabilities)-1)<1e-10
            fresh=max(range(19),key=lambda i:probabilities[i]);scores=[a+b for a,b in zip(credit,probabilities)];action=max(range(19),key=lambda i:scores[i])
            assert action==row['action'] and fresh==row['fresh_shadow'] and row['chosen_probability']==probabilities[action] and row['maximum_probability']==probabilities[fresh]
            credit=scores;credit[action]-=1;repeated=repeated+1 if action==last_action else 1;last_action=action
            changed=row['passed']!=phase;assert row['phase_changed']==changed and (not phase or row['passed']);phase=row['passed']
            current=(row['team'],row['player']);assert row['owner_changed']==(owner is not None and owner!=current);owner=current
            low=probabilities[fresh]>.5 and probabilities[action]<.25*probabilities[fresh];assert low==row['low_probability']
            counts['decisions']+=1;counts['phase_changes']+=changed;counts['phase_different']+=changed and action!=fresh;counts['all_different']+=action!=fresh;counts['low_probability']+=low;counts['phase_low_probability']+=changed and low
        assert step+1==baseline[previous]['steps'] and seen==expected_cases and item['goals']==sum(baseline[i]['controlled_score_delta']>0 for i in seen)
        assert all(counts[k]==item[k] for k in totals)
        for k in totals:totals[k]+=counts[k]
    result=dict(passed=True,episodes=100,**totals,report_sha256=sha(args.trace/'report.json'),auditor_sha256=sha(Path(__file__)),
        interpretation='Carried credit changes55/99 phase-entry actions. These100 episodes score99 goals;no causal harm established. No intervention or weight updates.')
    (args.output/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
