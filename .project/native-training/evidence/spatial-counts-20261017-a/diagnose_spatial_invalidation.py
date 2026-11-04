"""Count real spatial cache state without changing or skipping engine methods."""
import argparse
import ctypes
import json
import multiprocessing
import os
from pathlib import Path
import shlex
import sys
import validate

def probed_worker(channel,config):
    from gfootball.training_workers import _worker_main
    from gfootball.owned_engine import OwnedEngine
    library=ctypes.CDLL(os.environ['FOOTBALL_SPATIAL_PROBE_LIBRARY'])
    switch=library.football_spatial_phase
    switch.argtypes=[ctypes.c_uint]; switch.restype=ctypes.c_uint
    original=OwnedEngine._invoke
    def invoke(self,name,*args,**kwargs):
        previous=switch({'step':1,'reset':2,'get_state_digest':3,'close':4}.get(name,0))
        try: return original(self,name,*args,**kwargs)
        finally: switch(previous)
    OwnedEngine._invoke=invoke
    return _worker_main(channel,config)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root',type=Path,required=True)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--updates',type=int,default=128)
    args=parser.parse_args()
    if not 4<=args.updates<=128: parser.error('updates must be in [4,128]')
    probe=args.probe.resolve(); probe_hash=validate.sha(probe)
    source=Path(__file__).with_name('spatial_invalidation_probe.cpp'); source_hash=validate.sha(source)
    directory=args.work_root.resolve().with_name(args.work_root.name+'-counters')
    directory.mkdir(parents=True,exist_ok=False)
    wrapper=directory/'python-probe'
    wrapper.write_text('#!/bin/sh\nexport LD_PRELOAD='+shlex.quote(str(probe))+'"${LD_PRELOAD:+:$LD_PRELOAD}"\nexec '+shlex.quote(sys.executable)+' "$@"\n')
    wrapper.chmod(0o700)
    os.environ.update(FOOTBALL_SPATIAL_PROBE_LIBRARY=str(probe),FOOTBALL_SPATIAL_PROBE_DIR=str(directory),
        FOOTBALL_SPATIAL_ENGINE=str(args.build_root.resolve()/'validation-stage/gfootball_engine/libfootball_engine.so'))
    multiprocessing.set_executable(str(wrapper))
    sys.path.insert(0,str(validate.ROOT))
    import gfootball.training_workers as workers
    workers._worker_main=probed_worker
    import profile_matched_ppo
    sys.argv=[str(Path(profile_matched_ppo.__file__)),'--build-root',str(args.build_root),
        '--work-root',str(args.work_root),'--output',str(args.output),'--workers','4',
        '--updates',str(args.updates),'--seconds','600']
    code=profile_matched_ppo.main()
    if code: return code
    assert validate.sha(probe)==probe_hash and validate.sha(source)==source_hash
    output=args.output.resolve(); run=json.loads((output/'report.json').read_text())
    pids=list(run['resources'][0]['workers'])
    data={pid:json.loads((directory/f'spatial-{pid}.json').read_text()) for pid in pids}
    expected=str(args.build_root.resolve()/'validation-stage/gfootball_engine/libfootball_engine.so')
    for pid,worker in data.items():
        assert worker['pid']==int(pid) and worker['origin']==expected
        assert sum(sum(phase['invalidations']) for phase in worker['phases'])>0
        assert sum(phase['node_calls'] for phase in worker['phases'])>0
    summary=dict(passed=True,scope='Instrumented actual worker lifetimes, all original methods/guards execute. Phase set around OwnedEngine invocation. Includes pool warmup/construction; not throughput evidence. Dirty flags alone do not prove pruning safe.',
        measured_worker_pids=pids,workers=data,probe_sha256=probe_hash,probe_source_sha256=source_hash,
        probe_library=str(probe),files={str(directory/f'spatial-{pid}.json'):validate.sha(directory/f'spatial-{pid}.json') for pid in pids},
        phase_names=['other','step','reset','digest','close','unused'],dirty_mask='position=1 rotation=2 scale=4; 7 means all three dirty on entry',
        root_counter_scope='Outermost intercepted Node update; includes every cause, not just Mirror. Partial descendant refers to transform flags, not full observer/AABB semantics.')
    (output/'spatial-counters.json').write_text(json.dumps(summary,indent=2)+'\n')
    for file in (Path(__file__),source): (output/file.name).write_bytes(file.read_bytes())
    print(json.dumps(dict(passed=True,workers=pids)))
    return 0
if __name__=='__main__': raise SystemExit(main())
