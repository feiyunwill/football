"""New-process frozen-load check for the sustained diagnostic learner checkpoint."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import validate

def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); evidence=args.evidence.resolve()
    report=json.loads((evidence/'report.json').read_text())
    assert report['passed'] and report['source_after']==validate.source_fingerprint()
    path=evidence/'latest-checkpoint.json'; before=validate.sha(path)
    assert before==report['checkpoint_sha256']
    saved=json.loads(path.read_text())
    extension=next(Path(p) for p in report['artifacts'] if Path(p).name.startswith('_ppo_worker_core'))
    assert validate.sha(extension)==report['artifacts'][str(extension)]==saved['identity']['core']
    assert saved['identity']['source']==report['source_after']['sha256']
    assert saved['next_update']==report['updates']==saved['state']['version']
    sys.path.insert(0,str(extension.parent))
    import _ppo_worker_core
    assert Path(_ppo_worker_core.__file__).resolve()==extension
    learner=_ppo_worker_core.Core(11,1); learner.restore(saved['state'])
    payload=canonical(learner.state()); assert payload==canonical(saved['state'])
    actions=learner.decide(np.zeros((11,115),dtype=np.float32),42,0)
    assert len(actions)==11 and all(0<=a<19 for a in actions)
    assert canonical(learner.state())==payload and validate.sha(path)==before
    args.output.mkdir(parents=True,exist_ok=False)
    result=dict(passed=True,scope='new-process frozen learner load; not resumed training equivalence or football evaluation',
        checkpoint_sha256=before,payload_sha256=hashlib.sha256(payload).hexdigest(),version=saved['next_update'],
        runner_sha256=validate.sha(Path(__file__)),source_sha256=report['source_after']['sha256'])
    (args.output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    (args.output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,version=saved['next_update'])))
    return 0
if __name__=='__main__': raise SystemExit(main())
