"""Build a diagnostic probe with a checked engine/header ABI receipt."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import validate
HEADERS=('engine/src/types/spatial.hpp','engine/src/scene/scene3d/node.hpp',
         'engine/src/scene/object.hpp','engine/src/types/refcounted.hpp',
         'engine/src/base/math/vector3.hpp','engine/src/base/math/quaternion.hpp')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); build=args.build_root.resolve(); output=args.output.resolve()
    if output==validate.ROOT or validate.ROOT in output.parents: parser.error('output must be external')
    output.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).with_name('spatial_invalidation_probe.cpp')
    engine=build/'validation-stage/gfootball_engine/libfootball_engine.so'
    before={name:validate.sha(validate.ROOT/name) for name in HEADERS}
    engine_hash=validate.sha(engine); source_hash=validate.sha(source)
    entry=next(x for x in json.loads((build/'compile_commands.json').read_text()) if x['file'].endswith('/scene3d/node.cpp'))
    argv=shlex.split(entry['command']); command=[]; i=0
    while i<len(argv):
        if argv[i]=='-o': i+=2; continue
        if argv[i]=='-c' or argv[i]==entry['file']: i+=1; continue
        command.append(argv[i]); i+=1
    library=output/'spatial_probe.so'
    command+=['-shared',str(source),'-ldl','-o',str(library)]
    result=subprocess.run(command,cwd=entry['directory'],capture_output=True,text=True)
    (output/'build.log').write_text(result.stdout+result.stderr); result.check_returncode()
    assert before=={name:validate.sha(validate.ROOT/name) for name in HEADERS}
    assert engine_hash==validate.sha(engine) and source_hash==validate.sha(source)
    receipt=dict(build_root=str(build),engine_sha256=engine_hash,headers=before,
        source_sha256=source_hash,library_sha256=validate.sha(library),argv=command)
    library.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(library)
    return 0
if __name__=='__main__': raise SystemExit(main())
