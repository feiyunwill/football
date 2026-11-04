"""Independent audit of the Schema12 group-4 action trace diagnostic."""
import argparse,json
from pathlib import Path
import quality
from validate import sha,source_fingerprint
def read(path):return json.loads(path.read_text())
def rows(path):return [json.loads(line) for line in path.read_text().splitlines()]
def main():
  parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--diagnostic',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();root=args.diagnostic.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);result=dict(passed=False)
  try:
    protocol=read(root/'protocol.json');report=read(root/'report.json');quality.verify(Path(protocol['quality']['report']).resolve())
    assert report['passed'] and report['source_before']==report['source_after']==protocol['source']==source_fingerprint() and protocol['selected']==list(range(160,200))
    assert protocol['selection']=='all already-evaluated group-4 cases; mechanism diagnosis only; no candidate selection' and not protocol['confirmation_opened']
    assert sha(root/'protocol.json')==report['protocol_sha256'] and all(sha(Path(path))==digest for path,digest in protocol['frozen'].items())
    study=read(Path(protocol['study'])/'report.json');assert study['passed'] and not study['validation_passed']
    assert len(report['commands'])==5 and all(row['exit_code']==0 and sha(root/f"trace-{row['seed']}.jsonl")==row['stdout_sha256'] and sha(root/f"trace-{row['seed']}.stderr")==row['stderr_sha256'] for row in report['commands'])
    summary={}
    for seed in (42,123,2026,31415,271828):
      data=rows(root/f'trace-{seed}.jsonl');assert len(data)==40 and [row['index'] for row in data]==protocol['selected'] and all(row['group']==4 and 1<=len(row['actions'])<=8 for row in data)
      expected=next(row for row in study['validation'] if row['seed']==seed)['groups'][4];goals=sum(row['score']>0 for row in data);assert goals==expected==report['diagnosis'][str(seed)]['goals']
      initial={str(action):sum(row['actions'][0]==action for row in data) for action in range(19)};failure={str(action):sum(row['score']<=0 and row['actions'][0]==action for row in data) for action in range(19)}
      assert initial==report['diagnosis'][str(seed)]['initial_actions'] and failure==report['diagnosis'][str(seed)]['failure_initial_actions'];summary[str(seed)]=dict(goals=goals,failures=40-goals,initial_actions=initial)
    result.update(passed=True,summary=summary,diagnostic_report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),source_sha256=protocol['source']['sha256'],auditor_sha256=sha(Path(__file__)))
  except BaseException as error:result['error']=f'{type(error).__name__}: {error}'
  (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
