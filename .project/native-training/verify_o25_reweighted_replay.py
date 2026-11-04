"""Gated current-source delivery:relocated/archive primary replay and real continuation."""
import argparse,json,os,re,shutil,subprocess,tarfile,time
from pathlib import Path
import quality
from validate import ROOT,sha,source_fingerprint

SEEDS=(42,123,2026,31415,271828)
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2)+'\n')
def require_bundled_core(text,bundle):
    assert 'not found' not in text and 'libpython' not in text
    line=next(line for line in text.splitlines() if line.strip().startswith('libfootball_engine.so =>'))
    resolved=Path(line.split('=>',1)[1].strip().split(' (',1)[0]).resolve()
    assert resolved==(bundle/'libfootball_engine.so').resolve()

def records(path):
    lines=path.read_text().splitlines();data=[json.loads(s) for s in lines];summary=data.pop()
    assert summary.get('summary') and summary['complete'] and len(data)==200 and summary['episodes']==200
    return data,summary,lines[:-1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('study','confirmation','audit','stability','stability-audit','delivery','quality','build','output'):
        ap.add_argument('--'+key,type=Path,required=True)
    a=ap.parse_args();current=source_fingerprint();quality.verify(a.quality/'report.json')
    study=read(a.study/'report.json');training=read(a.study/'protocol.json');assert Path(training['build']).resolve()==a.build.resolve() and training['source']==current
    assessment=read(a.confirmation/'report.json');audit=read(a.audit/'report.json')
    confirmation=read(a.confirmation/'protocol.json');stable=read(a.stability/'report.json');sp=read(a.stability/'protocol.json')
    stability_audit=read(a.stability_audit/'report.json');assert stability_audit['passed'] and stability_audit['report_sha256']==sha(a.stability/'report.json') and stability_audit['protocol_sha256']==sha(a.stability/'protocol.json')
    assert stability_audit['source_sha256']==current['sha256']
    delivery=read(a.delivery/'report.json')
    assert study['passed'] and study['validation_passed'] and study['selected']=='reweighted_mean4'
    assert assessment['passed'] and assessment['confirmation_passed'] and audit['passed'] and audit['confirmation_passed']
    assert audit['report_sha256']==sha(a.confirmation/'report.json') and audit['protocol_sha256']==sha(a.confirmation/'protocol.json')
    assert confirmation['study_report_sha256']==sha(a.study/'report.json')
    for r in (study,assessment,stable,delivery):assert r['source_before']==r['source_after']==current
    assert stable['passed'] and all(stable['gates'].values()) and stable['native']['seconds']>=3600 and stable['child_reaped']
    assert not stable['build_observations'] and not stable['descendant_pids']
    assert sp['source']==current and sp['duration_seconds']==3600
    assert delivery['passed'] and delivery['source_kind']=='exact_current_worktree_not_committed_HEAD'
    assert delivery['validator_sha256']==sha(Path(__file__).with_name('validate_current_delivery.py'))
    assert delivery['snapshot_tool_sha256']==sha(Path(__file__).with_name('snapshot_current.py'))
    for registration in (training,confirmation,sp):assert all(sha(Path(f))==h for f,h in registration['frozen'].items())
    for c in delivery['commands']:assert c['exit_code']==0 and sha(a.delivery/c['log'])==c['sha256']
    quality_report=read(a.quality/'report.json');quality_log=(a.quality/'python-integration.log').read_text();installed_log=(a.delivery/'installed-integration.log').read_text()
    qmatch=re.search(r'^Ran (\d+) tests in ',quality_log,re.MULTILINE);imatch=re.search(r'^Ran (\d+) tests in ',installed_log,re.MULTILINE)
    assert qmatch and imatch and int(qmatch[1])==int(imatch[1])
    for name in ('test_annealed_global_clock_resume_and_task_identity','test_reweighted_global_clock_resume_and_task_identity'):
        assert any(line.startswith(name+' (') and line.endswith(' ... ok') for line in quality_log.splitlines())
        assert any(line.startswith(name+' (') and line.endswith(' ... ok') for line in installed_log.splitlines())
    original=Path(delivery['native_package']['path']);native_manifest=delivery['native_package']['manifest']['files']
    assert all(sha(original/name)==h for name,h in native_manifest.items())
    models={m['seed']:m for m in study['models']};assert set(models)==set(SEEDS)
    assert sp['model_sha256']==models[42]['sha256'] and sp['derived_inference_policy_sha256']==models[42]['policy_sha256']
    source_archive=original.parent/'source.tar';wheel=original.parent/'wheels'/delivery['wheel']['name']
    assert sha(source_archive)==delivery['source_archive_sha256'] and sha(wheel)==delivery['wheel']['sha256']
    files=[source_archive,wheel,Path(__file__),Path(__file__).with_name('validate_current_delivery.py'),a.study/'report.json',a.study/'protocol.json',
           a.confirmation/'report.json',a.confirmation/'protocol.json',a.audit/'report.json',a.stability/'report.json',a.stability/'protocol.json',a.stability_audit/'report.json',
           a.delivery/'report.json',a.quality/'report.json',a.confirmation/'cases.json',a.confirmation/'cases.txt',
           a.build/'bin/native_ppo_train',a.build/'libfootball_engine.so']
    for seed,m in models.items():
        assert m['configuration']=='reweighted_mean4' and m['policy_kind']=='within_seed_mean4_v1' and m['final_version']==8192
        assert sha(Path(m['path']))==m['sha256'] and sha(Path(m['policy']))==m['policy_sha256']
        assert confirmation['models'][str(seed)]['candidate']['sha256']==m['policy_sha256']
        files.extend(Path(m[k]) for k in ('path','policy','raw_policy','provenance_manifest'))
        files.extend(Path(member[k]) for member in m['members'] for k in ('checkpoint','policy'))
        files.append(a.confirmation/f'{seed}-candidate.log')
    files.extend(a.quality/c['log'] for c in quality_report['commands'])
    files.extend(a.delivery/c['log'] for c in delivery['commands'])
    files.extend([a.stability/'training.log',a.stability/'training.stderr',a.stability/'resources.jsonl',a.stability/'continuous'])
    files.extend(a.stability/name for name in stable['checkpoint_manifest'])
    files.append(Path(__file__).with_name('snapshot_current.py'))
    for registration in (training,confirmation,sp):files.extend(Path(f) for f in registration['frozen'])
    frozen={str(p.resolve()):sha(p) for p in files}
    out=a.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    protocol=dict(source=current,frozen=frozen,original_native_manifest=native_manifest,primary_episodes_per_location=1000,
        locations=['independent-directory','actual-archive-extraction'],installed_tests_verified=int(imatch[1]),inference_resume_decisions=8,full_schema6_training_updates=64,
        split_schema6_training_updates=[32,32],command_wall_cap_seconds=1800,total_wall_cap_seconds=3600,
        scope='Current-source isolated installed build only. FPOL mean4 is inference-only;real original FPPO resumes with its matching copied runtime. No guard bypass or learning selection.')
    write(out/'protocol.json',protocol);report=dict(passed=False,source_before=current,protocol_sha256=sha(out/'protocol.json'),commands=[])
    clean={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH','FOOTBALL_INFERENCE_TRACE','FOOTBALL_INFERENCE_RESUME') and not k.startswith('GFOOTBALL_')}
    start=time.monotonic()
    def unchanged():assert source_fingerprint()==current and all(sha(Path(p))==h for p,h in frozen.items())
    def run(name,argv):
        unchanged();assert time.monotonic()-start<3600;print(name,flush=True);begin=time.monotonic()
        log=out/(name+'.log');errors=out/(name+'.stderr')
        with log.open('w') as stream,errors.open('w') as err:
            result=subprocess.run(list(map(str,argv)),cwd=out,env=clean,stdout=stream,stderr=err,timeout=min(1800,3600-(time.monotonic()-start)))
        report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=result.returncode,seconds=time.monotonic()-begin,
            stdout_sha256=sha(log),stderr_sha256=sha(errors)))
        assert result.returncode==0,(name,errors.read_text()[-3000:]);return log
    try:
        artifacts=out/'artifacts';artifacts.mkdir();shutil.copyfile(source_archive,artifacts/'source.tar');shutil.copyfile(wheel,artifacts/wheel.name)
        assert sha(artifacts/'source.tar')==delivery['source_archive_sha256'] and sha(artifacts/wheel.name)==delivery['wheel']['sha256']
        package=out/'native-package';shutil.copytree(original,package)
        assert all(sha(package/name)==h for name,h in native_manifest.items())
        inference=package/'inference';inference.mkdir()
        for name in ('cases.json','cases.txt'):shutil.copyfile(a.confirmation/name,inference/name)
        shutil.copyfile(a.confirmation/'protocol.json',inference/'confirmation-protocol.json')
        trained=package/'trained-states';trained.mkdir();mapping={};expected=[]
        for seed,m in models.items():
            shutil.copyfile(Path(m['policy']),inference/f'policy-{seed}.fpol')
            shutil.copyfile(Path(m['provenance_manifest']),inference/f'provenance-{seed}.json')
            target=trained/str(seed);target.mkdir()
            for member in m['members']:
                for key,suffix in (('checkpoint','fppo'),('policy','fpol')):
                    src=Path(member[key]);dest=target/f'{member["version"]}.{suffix}';shutil.copyfile(src,dest)
                    assert sha(dest)==sha(src);mapping[sha(src)]=str(dest.relative_to(package))
            golden,summary,raw=records(a.confirmation/f'{seed}-candidate.log')
            expected_path=inference/f'expected-{seed}.jsonl';expected_path.write_text(''.join(s+'\n' for s in raw))
            expected.append(f'{sha(expected_path)}  {seed}.jsonl')
        write(inference/'provenance-locations.json',mapping)
        (inference/'expected-episodes.sha256').write_text('\n'.join(expected)+'\n')
        runtime=package/'compatible-training';(runtime/'bin').mkdir(parents=True)
        shutil.copy2(a.build/'bin/native_ppo_train',runtime/'bin/native_ppo_train')
        shutil.copy2(a.build/'libfootball_engine.so',runtime/'libfootball_engine.so')
        launcher=runtime/'native_ppo_train'
        launcher.write_text('#!/bin/sh\nset -eu\nhere=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexport GFOOTBALL_DATA_DIR="$here/../data"\nexport GFOOTBALL_FONT="$here/../fonts/AlegreyaSansSC-ExtraBold.ttf"\nexec "$here/bin/native_ppo_train" "$@"\n');launcher.chmod(0o755)
        script=package/'reproduce-primary.sh'
        script.write_text('#!/bin/sh\nset -eu\nbundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\noutput=${1:?Usage: reproduce-primary.sh NEW_OUTPUT_DIRECTORY}\nmkdir -- "$output"\nfor seed in 42 123 2026 31415 271828; do\n  "$bundle/native_ppo_train" --inference-mode balanced --policy "$bundle/inference/policy-$seed.fpol" --inference-cases "$bundle/inference/cases.txt" > "$output/$seed.full.jsonl"\n  sed \'$d\' "$output/$seed.full.jsonl" > "$output/$seed.jsonl"\ndone\n(cd -- "$output" && sha256sum -c "$bundle/inference/expected-episodes.sha256")\n');script.chmod(0o755)
        (package/'STATE.md').write_text('Primary mean4 FPOL policies are portable inference weights,not training checkpoints. FIFS1 sessions include engine/controller/action state and must match policy,case and mode. Original FPPO states are in trained-states;continue them only with compatible-training/native_ppo_train and matching task6 configuration. The independent installed runtime also supports newly initialized schema6 training and full-state continuation. No compatibility checks are disabled. Wall time in JSON summaries is observational;episode rows and semantic summary fields must reproduce exactly.\n')
        run('relocated-linkage',['ldd',package/'bin/native_ppo_train'])
        require_bundled_core((out/'relocated-linkage.log').read_text(),package)
        run('compatible-runtime-linkage',['ldd',runtime/'bin/native_ppo_train'])
        require_bundled_core((out/'compatible-runtime-linkage.log').read_text(),runtime)
        run('relocated-primary-reproduction',[script,out/'relocated-replayed'])
        sessions=inference/'sessions';sessions.mkdir();resume_checks=[]
        for seed in SEEDS:
            actual,summary,raw=records(out/'relocated-replayed'/f'{seed}.full.jsonl');golden,gold_summary,gold_raw=records(a.confirmation/f'{seed}-candidate.log')
            assert actual==golden and raw==gold_raw
            assert {k:v for k,v in summary.items() if k!='wall_seconds'}=={k:v for k,v in gold_summary.items() if k!='wall_seconds'}
            common=[package/'native_ppo_train','--inference-mode','balanced','--policy',inference/f'policy-{seed}.fpol','--inference-cases',inference/'cases.txt']
            state=sessions/f'{seed}.fifs';prefix=run(f'inference-prefix-{seed}',[*common,'--inference-decisions',8,'--inference-state-out',state])
            partial=[json.loads(s) for s in prefix.read_text().splitlines()];partial_summary=partial.pop();assert not partial_summary['complete'] and partial_summary['decisions']==8 and partial_summary['episodes']==len(partial) and state.is_file()
            tail=run(f'inference-resume-{seed}',[*common,'--inference-state-in',state]);suffix,tail_summary,_=records_from_tail(tail)
            assert partial_summary['decisions']+tail_summary['decisions']==gold_summary['decisions'] and tail_summary['policy_sha256']==gold_summary['policy_sha256']
            assert partial+suffix==golden;resume_checks.append(dict(seed=seed,state_sha256=sha(state),prefix_episodes=len(partial),remaining_episodes=len(suffix)))
        common=['--scenario','2v1_broad_reweighted','--seed',42,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,'--cadence',10,'--episode-limit',256,'--no-initial-eval','--eval-episodes',0]
        full,prefix,resumed=[out/f'fresh-{s}.fppo' for s in ('full','prefix','resumed')]
        full_data=read(run('fresh-full64',[package/'native_ppo_train',*common,'--updates',64,'--save',full]))
        prefix_data=read(run('fresh-prefix32',[package/'native_ppo_train',*common,'--updates',32,'--save',prefix]))
        resumed_data=read(run('fresh-resume32',[package/'native_ppo_train',*common,'--updates',32,'--load',prefix,'--save',resumed]))
        assert full.read_bytes()==resumed.read_bytes() and full_data['iterations'][:32]==prefix_data['iterations'] and full_data['iterations'][32:]==resumed_data['iterations']
        assert all(row['optimizer_steps']==16 and row['learning_rate']==.0003*(1-(row['version']-1)/8192) for row in full_data['iterations'])
        assert full_data['version']==resumed_data['version']==64 and full_data['total_transitions']==16384
        trained_path=trained/'42/8192.fppo';continued=out/'relocated-original-8193.fppo'
        continued_data=read(run('original-compatible-continuation',[launcher,*common,'--updates',1,'--load',trained_path,'--save',continued]))
        assert continued_data['start_version']==8192 and continued_data['version']==8193 and continued_data['iterations'][0]['learning_rate']==.0003*.1
        manifest={str(p.relative_to(package)):sha(p) for p in package.rglob('*') if p.is_file()}
        write(package/'delivery-manifest.json',dict(source_sha256=current['sha256'],files=manifest))
        archive=artifacts/'football-o25-reweighted-native.tar.gz'
        with tarfile.open(archive,'w:gz') as stream:stream.add(package,arcname='football-native')
        extraction=out/'archive-extracted';extraction.mkdir()
        with tarfile.open(archive) as stream:stream.extractall(extraction,filter='data')
        extracted=extraction/'football-native';assert all(sha(extracted/f)==h for f,h in manifest.items())
        run('archive-primary-reproduction',[extracted/'reproduce-primary.sh',out/'archive-replayed'])
        for seed in SEEDS:
            actual,summary,_=records(out/'archive-replayed'/f'{seed}.full.jsonl');golden,gold_summary,_=records(a.confirmation/f'{seed}-candidate.log');assert actual==golden
            assert {k:v for k,v in summary.items() if k!='wall_seconds'}=={k:v for k,v in gold_summary.items() if k!='wall_seconds'}
            path=run(f'archive-inference-resume-{seed}',[extracted/'native_ppo_train','--inference-mode','balanced','--policy',extracted/f'inference/policy-{seed}.fpol','--inference-cases',extracted/'inference/cases.txt','--inference-state-in',extracted/f'inference/sessions/{seed}.fifs'])
            suffix,tail_summary,_=records_from_tail(path);assert tail_summary['decisions']+8==gold_summary['decisions'] and tail_summary['policy_sha256']==gold_summary['policy_sha256'];original_prefix=[json.loads(s) for s in (out/f'inference-prefix-{seed}.log').read_text().splitlines()][:-1]
            assert original_prefix+suffix==golden
        archive_continued=out/'archive-original-8193.fppo'
        archive_data=read(run('archive-compatible-continuation',[extracted/'compatible-training/native_ppo_train',*common,'--updates',1,'--load',extracted/'trained-states/42/8192.fppo','--save',archive_continued]))
        assert archive_continued.read_bytes()==continued.read_bytes() and archive_data['iterations']==continued_data['iterations']
        unchanged();assert all(sha(package/f)==h and sha(extracted/f)==h for f,h in manifest.items())
        assert time.monotonic()-start<=3600
        report['delivered_artifacts']={p.name:sha(p) for p in artifacts.iterdir() if p.is_file()}
        (artifacts/'SHA256SUMS').write_text(''.join(f'{h}  {name}\n' for name,h in sorted(report['delivered_artifacts'].items())))
        report.update(passed=True,installed_tests_verified=int(imatch[1]),relocated_replayed_episodes=1000,archive_replayed_episodes=1000,inference_resume_checks=resume_checks,archive_inference_resume_models=5,
            fresh_training_full_split_bytes_equal=True,fresh_checkpoint_sha256=sha(full),compatible_trained_continuation_bytes_equal=True,
            trained_continuation_sha256=sha(continued),package=str(package),archive=str(archive),archive_sha256=sha(archive),package_manifest=manifest,package_manifest_sha256=sha(package/'delivery-manifest.json'),
            delivery_report_sha256=sha(a.delivery/'report.json'),confirmation_report_sha256=sha(a.confirmation/'report.json'),confirmation_audit_sha256=sha(a.audit/'report.json'),stability_report_sha256=sha(a.stability/'report.json'),stability_audit_sha256=sha(a.stability_audit/'report.json'))
    except BaseException as e:report['error']=f'{type(e).__name__}: {e}'
    finally:
        report['source_after']=source_fingerprint();report['seconds']=time.monotonic()-start
        try:unchanged()
        except BaseException as e:report.update(passed=False,error=f'Frozen source/evidence changed: {e}')
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','relocated_replayed_episodes','archive_replayed_episodes','error')}),flush=True)
    return 0 if report['passed'] else 1

def records_from_tail(path):
    lines=path.read_text().splitlines();data=[json.loads(s) for s in lines];summary=data.pop()
    assert summary.get('summary') and summary['complete'] and summary['episodes']==len(data) and len(data)<=200
    return data,summary,lines[:-1]

if __name__=='__main__':raise SystemExit(main())
