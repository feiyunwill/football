"""Sample native spawn workers independently; diagnostic only, not a speed test."""
import argparse
import json
import multiprocessing
from pathlib import Path
import shlex
import sys
import profile_matched_ppo

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root',type=Path,required=True)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--updates',type=int,default=128)
    args=parser.parse_args()
    if not 4<=args.updates<=512: parser.error('updates must be in [4,512]')
    collection=args.work_root.resolve().with_name(args.work_root.name+'-profiles')
    collection.mkdir(parents=True,exist_ok=False)
    wrapper=collection/'python-profile'
    wrapper.write_text('#!/bin/sh\nexec /usr/sbin/gprofng collect app -p 10 -F off -a off -o '+shlex.quote(str(collection))+'/worker-$$.er '+shlex.quote(sys.executable)+' "$@"\n')
    wrapper.chmod(0o700)
    multiprocessing.set_executable(str(wrapper))
    sys.argv=[str(Path(profile_matched_ppo.__file__)), '--build-root',str(args.build_root),
        '--work-root',str(args.work_root),'--output',str(args.output),'--workers','4',
        '--updates',str(args.updates),'--seconds','600']
    code=profile_matched_ppo.main()
    if code: return code
    output=args.output.resolve()
    run=json.loads((output/'report.json').read_text())
    pids=list(run['resources'][0]['workers'])
    profiles={pid:str(collection/f'worker-{pid}.er') for pid in pids}
    if not all(Path(path).is_dir() for path in profiles.values()):
        raise RuntimeError('Actual pool PID does not match collector artifact')
    (output/'native-profiles.json').write_text(json.dumps(dict(
        scope='Independent gprofng per spawn process; actual pool includes imports, construction, warmup, resets, steps and close; excludes parent PPO. Instrumented, not speed evidence.',
        measured_worker_pids=pids,profiles=profiles,period_ms=10,follow_descendants=False),indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    return 0
if __name__=='__main__': raise SystemExit(main())
