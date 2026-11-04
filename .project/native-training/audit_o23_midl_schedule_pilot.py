"""Independent checks for the schema8 checkpoint-schedule cost pilot."""
import argparse,json
from pathlib import Path
import quality
from validate import sha,source_fingerprint

def read(path): return json.loads(path.read_text())
def lines(path): return read(path)['iterations']
def main():
  parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--pilot',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();root=args.pilot.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);result={'passed':False}
  try:
    protocol=read(root/'protocol.json');report=read(root/'report.json');quality.verify(Path(report['quality']['report']) if 'report' in report['quality'] else Path(protocol['frozen']).parent)
    assert protocol['scenario']=='2v1_broad_reweighted_midl' and protocol['schema']==8 and protocol['updates']==1024 and protocol['reference_schedule']==[256]*4 and protocol['candidate_schedule']==[1024]
    assert report['passed'] and report['source_before']==report['source_after']==protocol['source']==source_fingerprint()
    assert sha(root/'protocol.json')==report['protocol_sha256'] and all(sha(Path(path))==digest for path,digest in protocol['frozen'].items())
    assert len(report['commands'])==5 and all(item['exit_code']==0 for item in report['commands'])
    for item in report['commands']: assert sha(root/(item['name']+'.log'))==item['stdout_sha256'] and sha(root/(item['name']+'.stderr'))==item['stderr_sha256']
    assert (root/'continuous.fppo').read_bytes()==(root/'split-u1024.fppo').read_bytes() and (root/'continuous.fpol').read_bytes()==(root/'split.fpol').read_bytes()
    assert lines(root/'continuous1024.log')==[item for target in (256,512,768,1024) for item in lines(root/f'split-u{target}.log')]
    assert report['checkpoint_bytes_equal'] and report['policy_bytes_equal'] and report['iterations_equal'] and report['continuous_seconds']<report['split_seconds'] and report['peak_child_rss']<=protocol['rss_cap_bytes'] and report['total_seconds']<=protocol['wall_cap_seconds']
    result.update(passed=True,report_sha256=sha(root/'report.json'),source_sha256=protocol['source']['sha256'],continuous_seconds=report['continuous_seconds'],split_seconds=report['split_seconds'],projected_continuous8192_seconds=report['continuous_projected8192_seconds'])
  except BaseException as error: result['error']=f'{type(error).__name__}: {error}'
  (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
