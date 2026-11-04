"""Independent schema6 study audit:160 chunks,LR,exact-rational mean4 and gates."""
import argparse,json,math
from fractions import Fraction
from audit_o23_averaging import decode
from pathlib import Path
import quality
from validate import sha,source_fingerprint
from audit_o23_study import native_start
SEEDS=(42,123,2026,31415,271828)
def read(p):return json.loads(p.read_text())
def lines(p):return [json.loads(s) for s in p.read_text().splitlines()]
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.study;out=args.output;out.mkdir(parents=True,exist_ok=False);result=dict(passed=False,validation_passed=False)
    try:
        p=read(root/'protocol.json');r=read(root/'report.json');quality.verify(Path(p['quality'])/'report.json')
        assert r['passed'] and r['source_before']==r['source_after']==p['source']==source_fingerprint()
        assert sha(root/'protocol.json')==r['protocol_sha256'] and all(sha(Path(path))==h for path,h in p['frozen'].items())
        assert r['training_seconds']<=p['budget']['max_total_training_wall_seconds'] and sha(root/'resources.jsonl')==r['resources_sha256']
        assert sum(path.stat().st_size for path in root.rglob('*') if path.is_file())<=2*1024**3
        assert 0<p['budget']['max_wall_seconds_per_training_run']<=5113 and p['budget']['max_total_training_wall_seconds']==5*p['budget']['max_wall_seconds_per_training_run']
        budget=read(Path(p['budget_receipt']));assert all(sha(Path(f))==h for f,h in budget['frozen'].items());assert budget['passed'] and budget['budget']==p['budget'] and budget['source_sha256']==p['source']['sha256']
        assert sha(Path(p['budget_receipt']))==p['frozen'][p['budget_receipt']]
        assert len(r['commands'])==180 and all(c['exit_code']==0 and c['observed_peak_rss']<=512*1024*1024 for c in r['commands'])
        for c in r['commands']:
            assert sha(root/(c['name']+'.log'))==c['stdout_sha256'] and sha(root/(c['name']+'.stderr'))==c['stderr_sha256']
        assert len(r['regressions'])==10 and r['portable_regression_passed']
        for baseline in p['baselines']:
            path=Path(baseline['policy']);assert sha(path)==baseline['policy_sha256'] and sha(Path(baseline['reference_log']))==baseline['reference_sha256']
            raw=lines(root/f'regression-{baseline["label"]}-{baseline["seed"]}.log');summary=raw.pop();expected=lines(Path(baseline['reference_log']));expected.pop()
            assert summary['complete'] and summary['policy_sha256']==baseline['policy_sha256'] and len(raw)==200 and raw==expected
        assert [(m['configuration'],m['seed']) for m in r['models']]==[('reweighted_mean4',seed) for seed in SEEDS]
        pilot=read(Path(p['pilot'])/'report.json');pilot_audit=read(Path(p['pilot_audit'])/'report.json')
        assert pilot['passed'] and pilot_audit['passed'] and pilot_audit['report_sha256']==sha(Path(p['pilot'])/'report.json')
        metadata=[];ppo=None;cells=[];ids=[tuple(map(int,s.split()[:2]+[s.split()[3]])) for s in (root/'cases.txt').read_text().splitlines()]
        for model in r['models']:
            seed=model['seed'];assert model['initial_version']==0 and model['final_version']==8192 and model['training_seconds']<=p['budget']['max_wall_seconds_per_training_run'] and len(model['chunks'])==32
            completed=0
            for index,target in enumerate(range(256,8193,256)):
                data=read(root/f'train-reweighted-{seed}-u{target}.log');checkpoint=root/f'models/reweighted-{seed}-u{target}.fppo'
                assert data['scenario']=='2v1_broad_reweighted' and data['seed']==seed and data['hidden']==64 and data['cadence']==10 and data['episode_limit']==256
                assert data['start_version']==target-256 and data['version']==target and data['total_transitions']==target*256
                if ppo is None:ppo=data['ppo']
                assert data['ppo']==ppo and data['ppo']['learning_rate']==.0003 and data['ppo']['epochs']==4 and data['ppo']['minibatch']==64
                assert data['state_before_evaluation_sha256']==data['state_sha256']==sha(checkpoint)==model['chunks'][index]['checkpoint_sha256']
                assert data['evaluation']['isolated'] and int.from_bytes(checkpoint.read_bytes()[44:48],'little')==6
                assert [row['version'] for row in data['iterations']]==list(range(target-255,target+1))
                for row in data['iterations']:
                    expected_lr=.0003*max(.1,(8193-row['version'])/8192)
                    assert row['learning_rate']==expected_lr and row['optimizer_steps']==16 and row['transitions']==256
                    assert all(math.isfinite(row[k]) for k in ('loss','entropy','gradient_norm','parameter_delta'))
                    completed+=row['completed_episodes']
                if seed==42 and target==256:assert data['iterations'][:64]==read(Path(p['pilot'])/'full64.log')['iterations']
            assert sha(Path(model['path']))==model['sha256'] and sha(Path(model['policy']))==model['policy_sha256']
            assert model['policy_kind']=='within_seed_mean4_v1' and sha(Path(model['raw_policy']))==model['raw_policy_sha256']
            raw_seed,raw_hidden,raw_provenance,_=decode(Path(model['raw_policy']))
            assert raw_seed==seed and raw_hidden==64 and raw_provenance==model['sha256']
            manifest=Path(model['provenance_manifest']);provenance=read(manifest)
            assert sha(manifest)==model['provenance_sha256'] and provenance['members']==model['members'] and provenance['seed']==seed and provenance['derived_inference_only']
            assert [m['version'] for m in model['members']]==[7424,7680,7936,8192] and all(m['weight']==.25 for m in model['members'])
            weights=[]
            for member in model['members']:
                cp,fp=Path(member['checkpoint']),Path(member['policy']);assert sha(cp)==member['checkpoint_sha256'] and sha(fp)==member['policy_sha256']
                assert cp.resolve()==(root/f'models/reweighted-{seed}-u{member["version"]}.fppo').resolve() and fp.resolve()==(root/f'models/reweighted-{seed}-u{member["version"]}.fpol').resolve()
                source_seed,hidden,identity,values=decode(fp);assert source_seed==seed and hidden==64 and identity==sha(cp);weights.append(values)
            derived_seed,hidden,identity,derived=decode(Path(model['policy']))
            expected=[float(sum((Fraction(value) for value in column),Fraction())/4) for column in zip(*weights)]
            assert derived_seed==seed and hidden==64 and identity==sha(manifest) and len(derived)==8724 and derived==expected
            starts=root/f'starts-reweighted_mean4-{seed}.log';assert sha(starts)==model['starts_sha256'];reconstructed=lines(starts)
            assert len(reconstructed)==completed+1==model['conservative_episode_starts']
            actual=native_start(Path(model['path']),seed,6,8192);assert actual['episode'] in (completed,completed-1)
            assert all(actual[k]==reconstructed[actual['episode']][k] for k in ('engine_seed','geometry','ball'))
            metadata.append(dict(seed=seed,version=8192,updates_with_lr_verified=8192,optimizer_steps_verified=131072,conservative_starts=len(reconstructed),native_start_matches=True,mean_parameters_verified=8724))
            rows=lines(root/f'validation-reweighted_mean4-{seed}.log');summary=rows.pop();assert summary['complete'] and len(rows)==200 and [(x['index'],x['group'],x['engine_seed']) for x in rows]==ids
            cells.append(dict(seed=seed,goals=sum(x['controlled_score_delta']>0 for x in rows),passes=sum(x['completed_passes']>0 for x in rows),joint=sum(x['completed_passes']>0 and x['controlled_score_delta']>0 for x in rows),groups=[sum(x['controlled_score_delta']>0 for x in rows if x['group']==g) for g in range(5)]))
        assert cells==r['validation'] and r['known_pilot_prefix_matches']
        total=sum(c['goals'] for c in cells);groups=[sum(c['groups'][g] for c in cells) for g in range(5)]
        old_report=Path(p['old_study'])/'report.json';assert sha(old_report)==p['frozen'][str(old_report)]
        legacy=sum(c['legacy']['success_count'] for c in read(old_report)['validation'])
        gates=dict(mean=total>=970,every_seed=all(c['goals']>=180 for c in cells),groups=all(n>=180 for n in groups),cooperation=all(c['passes']>=40 and c['joint']>=40 for c in cells),original_legacy_improvement=total>=legacy+20)
        assert gates==r['gates'] and all(gates.values())==r['validation_passed'] and total/1000==r['candidate_mean']
        result.update(passed=True,validation_passed=all(gates.values()),gates=gates,candidate_mean=total/1000,metadata=metadata,portable_regression_episodes=2000,report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),source_sha256=p['source']['sha256'],auditor_sha256=sha(Path(__file__)))
    except BaseException as error:result['error']=f'{type(error).__name__}: {error}'
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
