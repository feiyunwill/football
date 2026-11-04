"""Independently verify real global-clock updates,full restore,and schema guards."""
import argparse,json,hashlib
from pathlib import Path
import quality
from validate import sha,source_fingerprint
from audit_o23_study import native_start
def read(p):return json.loads(p.read_text())
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--pilot',type=Path,required=True);parser.add_argument('--quality',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.pilot;r=read(root/'report.json');p=read(root/'protocol.json');args.output.mkdir(parents=True,exist_ok=False)
    result=dict(passed=False)
    try:
        quality.verify(args.quality/'report.json')
        assert r['passed'] and r['source_before']==r['source_after']==p['source']==source_fingerprint()
        assert sha(root/'protocol.json')==r['protocol_sha256'] and all(sha(Path(path))==h for path,h in p['frozen'].items())
        assert r['total_seconds']<=1800 and sha(root/'resources.jsonl')==r['resources_sha256']
        assert len(r['commands'])==8
        for c in r['commands']:
            assert (c['exit_code']==1 if c['expected_failure'] else c['exit_code']==0) and c['observed_peak_rss']<=512*1024*1024
            assert sha(root/(c['name']+'.log'))==c['stdout_sha256'] and sha(root/(c['name']+'.stderr'))==c['stderr_sha256']
        full,prefix,resumed=[read(root/(name+'.log')) for name in ('full64','prefix32','resume32')]
        assert full['version']==resumed['version']==64 and prefix['version']==resumed['start_version']==32
        assert full['iterations'][:32]==prefix['iterations'] and full['iterations'][32:]==resumed['iterations']
        assert [row['version'] for row in full['iterations']]==list(range(1,65))
        for row in full['iterations']:
            assert row['learning_rate']==.0003*(8193-row['version'])/8192
            assert row['transitions']==256 and row['optimizer_steps']==16 and row['parameter_delta']>0
        assert (root/'full.fppo').read_bytes()==(root/'resumed.fppo').read_bytes() and (root/'full.fpol').read_bytes()==(root/'resumed.fpol').read_bytes()
        assert sha(root/'full.fppo')==r['checkpoint_sha256']==full['state_sha256']==full['state_before_evaluation_sha256']
        assert sha(root/'full.fpol')==r['policy_sha256']
        magic,checksum,payload=(root/'full.fpol').read_text().split('\n',2)
        assert magic=='FPOL1' and hashlib.sha256(payload.encode()).hexdigest()==checksum and payload.splitlines()[0].split()[-1]==sha(root/'full.fppo')
        assert 'variation/schema mismatch' in (root/'reject-new-task-as-constant.stderr').read_text()
        assert 'Incompatible training build or runtime dimensions' in (root/'reject-historical-source.stderr').read_text()
        starts=[json.loads(s) for s in (root/'pilot-starts.log').read_text().splitlines()];assert len(starts)==1+sum(row['completed_episodes'] for row in full['iterations'])
        actual=native_start(root/'full.fppo',42,5,64);expected=starts[actual['episode']];assert all(actual[k]==expected[k] for k in ('engine_seed','geometry','ball'))
        assert r['full_seconds']*128==r['projected8192_seconds']<=5113
        result.update(passed=True,global_lr_verified=True,full_state_and_policy_equal=True,updates_verified=64,optimizer_steps_verified=1024,strict_source_and_task_rejection=True,native_start_verified=True,
            report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),source_sha256=p['source']['sha256'],auditor_sha256=sha(Path(__file__)))
    except BaseException as error:result['error']=f'{type(error).__name__}: {error}'
    (args.output/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
