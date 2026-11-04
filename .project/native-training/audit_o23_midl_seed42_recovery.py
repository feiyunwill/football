"""Independently audit the non-candidate recovery of completed schema8 seed 42."""
import argparse,json
from pathlib import Path
from validate import sha,source_fingerprint
def read(p):return json.loads(p.read_text())
def main():
  p=argparse.ArgumentParser(description=__doc__);p.add_argument('--recovery',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.recovery.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);result={'passed':False}
  try:
    protocol=read(root/'protocol.json');report=read(root/'report.json');original=Path(protocol['original_study']);old=read(original/'report.json')
    assert report['passed'] and not report['candidate_accepted'] and protocol['seed']==report['seed']==42 and protocol['payload_schema']==8
    assert protocol['source']==source_fingerprint() and report['source_sha256']==protocol['source']['sha256'] and sha(root/'protocol.json')==report['protocol_sha256']
    assert all(sha(Path(path))==digest for path,digest in protocol['frozen'].items()) and sha(original/'report.json')==protocol['original_report_sha256']
    assert not old['passed'] and old['error']=="AssertionError: ('starts-midl_mean4-42', None)" and old['training_seconds']==report['training_seconds']<2520
    assert len(report['chunks'])==len(protocol['targets'])==11 and report['chunks'][-1]['version']==8192
    assert all(sha(Path(x['checkpoint']))==x['checkpoint_sha256'] for x in report['chunks'])
    assert sha(Path(report['starts']))==report['starts_sha256'] and len(Path(report['starts']).read_text().splitlines())==report['conservative_episode_starts']
    assert sha(Path(report['raw_checkpoint']))==report['raw_checkpoint_sha256'] and sha(Path(report['policy']))==report['policy_sha256'] and sha(Path(report['provenance_manifest']))==report['provenance_sha256']
    result.update(passed=True,candidate_accepted=False,report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),source_sha256=protocol['source']['sha256'],auditor_sha256=sha(Path(__file__)))
  except BaseException as error:result['error']=f'{type(error).__name__}: {error}'
  (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
