"""Independent audit for the preregistered Schema10 balanced-finisher five-seed study."""
import argparse,json,math
from fractions import Fraction
from pathlib import Path
import quality
from audit_o23_averaging import decode
from audit_o23_study import native_start
from validate import sha,source_fingerprint

SEEDS=(42,123,2026,31415,271828)

def read(path): return json.loads(path.read_text())
def lines(path): return [json.loads(line) for line in path.read_text().splitlines()]

def main():
  parser=argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--study',type=Path,required=True)
  parser.add_argument('--output',type=Path,required=True)
  args=parser.parse_args();root=args.study.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
  result=dict(passed=False,validation_passed=False)
  try:
    protocol=read(root/'protocol.json');report=read(root/'report.json')
    quality.verify(Path(protocol['quality'])/'report.json')
    assert protocol['scenario']=='2v1_broad_balanced_finisher' and protocol['payload_schema']==10
    assert protocol['lr']=='.0003*max(.1,1-global_version_before_update/8192)'
    assert protocol['seeds']==list(SEEDS) and protocol['updates_per_chunk']=='1024x7_then_256x4' and protocol['chunks']==11 and protocol['checkpoint_targets']==[1024,2048,3072,4096,5120,6144,7168,7424,7680,7936,8192] and protocol['final_version']==8192
    assert protocol['selection']=='Fixed within-seed equal mean of7424,7680,7936,8192; no alternative window' and 'prospective_cases' in protocol and 'frozen_o23_cases' not in protocol
    assert protocol['validation_gates']==dict(total=970,seed=180,group=180,passes=40,joint=40) and not protocol['confirmation_opened']
    assert protocol['helper_build']['command_count']==2 and protocol['helper_build']['ledger']=='setup_only_not_counted_in_180'
    helper=Path(protocol['helper_build']['output']);assert sha(helper)==protocol['helper_build']['output_sha256']==protocol['frozen'][str(helper)]
    assert report['passed'] and report['source_before']==report['source_after']==protocol['source']==source_fingerprint()
    assert sha(root/'protocol.json')==report['protocol_sha256'] and all(sha(Path(path))==digest for path,digest in protocol['frozen'].items())
    assert report['training_seconds']<=protocol['budget']['max_total_training_wall_seconds'] and sha(root/'resources.jsonl')==report['resources_sha256']
    assert sum(path.stat().st_size for path in root.rglob('*') if path.is_file())<=2*1024**3
    budget_receipt=Path(protocol['budget_receipt'])/'report.json';budget=read(budget_receipt);assert budget['passed'] and budget['budget']==protocol['budget'] and budget['source_sha256']==protocol['source']['sha256']
    assert all(sha(Path(path))==digest for path,digest in budget['frozen'].items()) and sha(budget_receipt)==protocol['frozen'][str(budget_receipt)]
    assert 0<protocol['budget']['max_wall_seconds_per_training_run']<=5113 and protocol['budget']['max_total_training_wall_seconds']==5*protocol['budget']['max_wall_seconds_per_training_run']
    assert len(report['commands'])==75 and all(row['exit_code']==0 and row['observed_peak_rss']<=512*1024*1024 for row in report['commands'])
    for row in report['commands']:
      assert sha(root/(row['name']+'.log'))==row['stdout_sha256'] and sha(root/(row['name']+'.stderr'))==row['stderr_sha256']
    assert len(report['regressions'])==10 and report['portable_regression_passed']
    for baseline in protocol['baselines']:
      policy,reference=Path(baseline['policy']),Path(baseline['reference_log'])
      assert sha(policy)==baseline['policy_sha256'] and sha(reference)==baseline['reference_sha256']
      actual=lines(root/f'regression-{baseline["label"]}-{baseline["seed"]}.log');summary=actual.pop();expected=lines(reference);expected.pop()
      assert summary['complete'] and summary['policy_sha256']==baseline['policy_sha256'] and len(actual)==200 and actual==expected
    assert [(model['configuration'],model['seed']) for model in report['models']]==[('balanced_finisher_mean4',seed) for seed in SEEDS]
    pilot=read(Path(protocol['pilot'])/'report.json');pilot_audit=read(Path(protocol['pilot_audit'])/'report.json')
    assert pilot['passed'] and pilot_audit['passed'] and pilot_audit['report_sha256']==sha(Path(protocol['pilot'])/'report.json')
    pilot_iterations=read(Path(protocol['pilot'])/'full64.log')['iterations'];metadata=[];cells=[];ppo=None
    assert sha(root/'cases.txt')==protocol['prospective_cases_sha256']
    receipt=read(Path(protocol['prospective_case_receipt']));assert receipt['passed'] and receipt['cases']==200 and receipt['groups']=={str(group):40 for group in range(5)} and receipt['case_sha256']==protocol['prospective_cases_sha256']==sha(root/'cases.txt') and sha(Path(protocol['prospective_case_receipt']))==protocol['prospective_case_receipt_sha256']
    ids=[tuple(map(int,line.split()[:2]+[line.split()[3]])) for line in (root/'cases.txt').read_text().splitlines()]
    for model in report['models']:
      seed=model['seed'];assert model['initial_version']==0 and model['final_version']==8192 and model['training_seconds']<=protocol['budget']['max_wall_seconds_per_training_run'] and len(model['chunks'])==len(protocol['checkpoint_targets'])
      completed=0;previous=0
      for index,target in enumerate(protocol['checkpoint_targets']):
        data=read(root/f'train-balanced-finisher-{seed}-u{target}.log');checkpoint=root/f'models/balanced-finisher-{seed}-u{target}.fppo'
        assert data['scenario']==protocol['scenario'] and data['seed']==seed and data['hidden']==64 and data['cadence']==10 and data['episode_limit']==256
        assert data['start_version']==previous and data['version']==target and data['total_transitions']==target*256
        if ppo is None: ppo=data['ppo']
        assert data['ppo']==ppo and data['ppo']['learning_rate']==.0003 and data['ppo']['epochs']==4 and data['ppo']['minibatch']==64
        assert data['state_before_evaluation_sha256']==data['state_sha256']==sha(checkpoint)==model['chunks'][index]['checkpoint_sha256']
        assert data['evaluation']['isolated'] and int.from_bytes(checkpoint.read_bytes()[44:48],'little')==10
        assert [row['version'] for row in data['iterations']]==list(range(previous+1,target+1))
        for row in data['iterations']:
          assert row['learning_rate']==.0003*max(.1,(8193-row['version'])/8192) and row['optimizer_steps']==16 and row['transitions']==256
          assert all(math.isfinite(row[key]) for key in ('loss','entropy','gradient_norm','parameter_delta'));completed+=row['completed_episodes']
        if seed==42 and target==1024: assert data['iterations'][:64]==pilot_iterations
        previous=target
      assert sha(Path(model['path']))==model['sha256'] and sha(Path(model['raw_policy']))==model['raw_policy_sha256'] and sha(Path(model['policy']))==model['policy_sha256']
      raw_seed,raw_hidden,raw_identity,_=decode(Path(model['raw_policy']));assert raw_seed==seed and raw_hidden==64 and raw_identity==model['sha256']
      manifest=Path(model['provenance_manifest']);provenance=read(manifest)
      assert model['policy_kind']=='within_seed_mean4_v1' and sha(manifest)==model['provenance_sha256'] and provenance['members']==model['members'] and provenance['seed']==seed and provenance['derived_inference_only']
      assert [member['version'] for member in model['members']]==[7424,7680,7936,8192] and all(member['weight']==.25 for member in model['members'])
      weights=[]
      for member in model['members']:
        checkpoint,policy=Path(member['checkpoint']),Path(member['policy'])
        assert sha(checkpoint)==member['checkpoint_sha256'] and sha(policy)==member['policy_sha256']
        assert checkpoint.resolve()==(root/f'models/balanced-finisher-{seed}-u{member["version"]}.fppo').resolve() and policy.resolve()==(root/f'models/balanced-finisher-{seed}-u{member["version"]}.fpol').resolve()
        member_seed,hidden,identity,values=decode(policy);assert member_seed==seed and hidden==64 and identity==sha(checkpoint);weights.append(values)
      derived_seed,hidden,identity,derived=decode(Path(model['policy']))
      expected=[float(sum((Fraction(value) for value in column),Fraction())/4) for column in zip(*weights)]
      assert derived_seed==seed and hidden==64 and identity==sha(manifest) and len(derived)==8724 and derived==expected
      starts=root/f'starts-balanced_finisher_mean4-{seed}.log';assert sha(starts)==model['starts_sha256'];reconstructed=lines(starts)
      assert len(reconstructed)==completed+1==model['conservative_episode_starts'];actual=native_start(Path(model['path']),seed,10,8192)
      assert actual['episode'] in (completed,completed-1) and all(actual[key]==reconstructed[actual['episode']][key] for key in ('engine_seed','geometry','ball'))
      metadata.append(dict(seed=seed,version=8192,updates_with_lr_verified=8192,optimizer_steps_verified=131072,conservative_starts=len(reconstructed),native_start_matches=True,mean_parameters_verified=8724))
      rows=lines(root/f'validation-balanced_finisher_mean4-{seed}.log');summary=rows.pop();assert summary['complete'] and len(rows)==200 and [(row['index'],row['group'],row['engine_seed']) for row in rows]==ids
      cells.append(dict(seed=seed,goals=sum(row['controlled_score_delta']>0 for row in rows),passes=sum(row['completed_passes']>0 for row in rows),joint=sum(row['completed_passes']>0 and row['controlled_score_delta']>0 for row in rows),groups=[sum(row['controlled_score_delta']>0 for row in rows if row['group']==group) for group in range(5)]))
    assert report['known_pilot_prefix_matches'] and cells==report['validation']
    total=sum(cell['goals'] for cell in cells);groups=[sum(cell['groups'][group] for cell in cells) for group in range(5)]
    gates=dict(mean=total>=970,every_seed=all(cell['goals']>=180 for cell in cells),groups=all(value>=180 for value in groups),cooperation=all(cell['passes']>=40 and cell['joint']>=40 for cell in cells))
    assert gates==report['gates'] and all(gates.values())==report['validation_passed'] and total/1000==report['candidate_mean'] and [value/200 for value in groups]==report['candidate_group_means']
    result.update(passed=True,validation_passed=all(gates.values()),gates=gates,candidate_mean=total/1000,metadata=metadata,portable_regression_episodes=2000,report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),source_sha256=protocol['source']['sha256'],auditor_sha256=sha(Path(__file__)))
  except BaseException as error:
    result['error']=f'{type(error).__name__}: {error}'
  (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
  return 0 if result['passed'] else 1

if __name__=='__main__': raise SystemExit(main())

