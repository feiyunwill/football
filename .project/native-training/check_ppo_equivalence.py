"""Exercise sample/minibatch and hidden-width tails against archived baseline libraries."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--experiment',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); work=args.work_root.resolve()
    original=json.loads(args.experiment.read_text()); cores={}
    for name in ('baseline','candidate'):
        path=work/f'{name}-paired.so'
        assert sha(path)==original['artifacts'][name+'-binary']
        lib=ctypes.CDLL(str(path),mode=os.RTLD_LOCAL|os.RTLD_DEEPBIND)
        run=lib.run_probe; run.argtypes=[ctypes.c_size_t]*4+[ctypes.c_char_p]; run.restype=ctypes.c_double
        cores[name]=(lib,run)
    rows=[]
    for players,hidden,count in ((1,1,1),(2,3,6),(11,7,65),(11,64,256)):
        states={}
        for name in cores:
            path=work/f'edge-{name}.bin'
            assert cores[name][1](players,hidden,count,1,os.fsencode(path))>0
            states[name]=sha(path)
        assert states['baseline']==states['candidate'], 'Numerical divergence'
        rows.append(dict(players=players,hidden=hidden,samples=count,state_sha256=states['baseline']))
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'report.json').write_text(json.dumps(dict(passed=True,rows=rows,
        experiment_sha256=sha(args.experiment),runner_sha256=sha(Path(__file__))),indent=2)+'\n')
    print(json.dumps(dict(passed=True,cases=len(rows))))
    return 0
if __name__=='__main__': raise SystemExit(main())
