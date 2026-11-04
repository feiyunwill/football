"""Bounded Schema15 checkpoint/resume pilot; it opens no acceptance data."""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

import quality
from validate import ROOT, runtime_identity, sha, source_fingerprint


def read(path): return json.loads(path.read_text())
def write(path, value): path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  for name in ('quality', 'build', 'output'): parser.add_argument('--' + name, type=Path, required=True)
  args = parser.parse_args(); verified = quality.verify(args.quality / 'report.json'); before = source_fingerprint()
  build, out = args.build.resolve(), args.output.resolve(); binary = build / 'bin/native_ppo_train'
  if out == ROOT or ROOT in out.parents: raise ValueError('output must be outside repository')
  if not binary.exists(): raise FileNotFoundError(binary)
  out.mkdir(parents=True, exist_ok=False)
  prereg = ROOT / '.project/optimization/o23-schema15-firststep-entropy-finisher-preregistration-20261029.md'
  files = [Path(__file__), prereg, args.quality / 'report.json', binary, build / 'libfootball_engine.so']
  frozen = {str(path.resolve()): sha(path) for path in files if path.exists()}
  protocol = dict(source=before, quality=verified, environment=runtime_identity(sys.executable), frozen=frozen,
    scenario='2v1_broad_firststep_entropy_finisher', schema=15, entropy_coefficient=.02,
    first_step_entropy_multiplier=2.5, seed=31415, hidden=64, epochs=4, minibatch=64,
    rollout=256, cadence=10, episode_limit=256, updates=1024, split=[512,512],
    wall_cap_seconds=1800, scope='Infrastructure/cost pilot only; no validation or confirmation cases.')
  write(out / 'protocol.json', protocol); started=time.monotonic(); commands=[]
  env=dict(os.environ, LD_LIBRARY_PATH=str(build), GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'), GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  def run(name, argv):
    log, err=out/(name+'.log'),out/(name+'.stderr'); begin=time.monotonic()
    with log.open('w') as stdout, err.open('w') as stderr:
      result=subprocess.run(list(map(str,argv)),cwd=build,env=env,stdout=stdout,stderr=stderr,timeout=max(1,protocol['wall_cap_seconds']-(time.monotonic()-started)))
    row=dict(name=name,argv=list(map(str,argv)),exit_code=result.returncode,seconds=time.monotonic()-begin,stdout_sha256=sha(log),stderr_sha256=sha(err));commands.append(row)
    assert result.returncode==0, row; return row['seconds']
  report=dict(passed=False,quality=verified,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=commands)
  try:
    common=[binary,'--scenario',protocol['scenario'],'--seed',31415,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,'--cadence',10,'--episode-limit',256,'--no-initial-eval']
    full_seconds=run('full1024',[*common,'--updates',1024,'--eval-episodes',0,'--save',out/'full.fppo','--export-policy',out/'full.fpol'])
    run('prefix512',[*common,'--updates',512,'--eval-episodes',0,'--save',out/'prefix.fppo'])
    run('resume512',[*common,'--updates',512,'--eval-episodes',0,'--load',out/'prefix.fppo','--save',out/'resumed.fppo','--export-policy',out/'resumed.fpol'])
    full,prefix,resumed=[read(out/(name+'.log')) for name in ('full1024','prefix512','resume512')]
    assert (out/'full.fppo').read_bytes()==(out/'resumed.fppo').read_bytes()
    assert (out/'full.fpol').read_bytes()==(out/'resumed.fpol').read_bytes()
    assert full['iterations'][:512]==prefix['iterations'] and full['iterations'][512:]==resumed['iterations']
    assert full['version']==resumed['version']==1024 and resumed['start_version']==512
    assert int.from_bytes((out/'full.fppo').read_bytes()[44:48],'little')==15
    for data in (full,prefix,resumed): assert data['scenario']==protocol['scenario'] and data['ppo']['entropy_coefficient']==.02
    run('pilot-holdout-eval',[*common,'--updates',0,'--load',out/'full.fppo','--eval-partition','holdout','--eval-seed',904730,'--eval-episodes',64,'--eval-steps',256])
    evaluation=read(out/'pilot-holdout-eval.log'); assert evaluation['evaluation']['isolated'] and evaluation['state_before_evaluation_sha256']==evaluation['state_sha256']
    report.update(passed=True,resume_bytes_equal=True,policy_bytes_equal=True,iterations_equal=True,checkpoint_sha256=sha(out/'full.fppo'),policy_sha256=sha(out/'full.fpol'),full_seconds=full_seconds,projected8192_seconds=full_seconds*8,transitions_per_second=262144/full_seconds)
  except BaseException as error: report['error']=f'{type(error).__name__}: {error}'
  report['source_after']=source_fingerprint(); report['total_seconds']=time.monotonic()-started
  if before!=report['source_after'] or any(sha(Path(path))!=digest for path,digest in frozen.items()): report.update(passed=False,error='Frozen source or evidence changed')
  write(out/'report.json',report); print(json.dumps({key:report.get(key) for key in ('passed','full_seconds','projected8192_seconds','error')})); return 0 if report['passed'] else 1
if __name__=='__main__': raise SystemExit(main())
