"""Run the bounded Schema14 entropy-high pilot without opening acceptance data."""
import argparse, json, math, os, psutil, subprocess, sys, time
from pathlib import Path

import quality
from validate import ROOT, runtime_identity, sha, source_fingerprint


def read(path):
  return json.loads(path.read_text())


def write(path, value):
  path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  for key in ('quality', 'build', 'output'):
    parser.add_argument('--' + key, type=Path, required=True)
  args = parser.parse_args()
  verified = quality.verify(args.quality / 'report.json')
  before = source_fingerprint()
  build, out = args.build.resolve(), args.output.resolve()
  binary = build / 'bin/native_ppo_train'
  if not binary.exists():
    binary = ROOT / 'bin/native_ppo_train'
  if out == ROOT or ROOT in out.parents:
    raise ValueError('pilot output must be outside the repository')
  out.mkdir(parents=True, exist_ok=False)
  preregistration = ROOT / '.project/optimization/o23-schema14-entropy-high-finisher-preregistration-20261029.md'
  files = [Path(__file__), Path(__file__).with_name('audit_o23_schema14_entropy_high_finisher_pilot.py'), preregistration, args.quality / 'report.json', binary, build / 'libfootball_engine.so']
  frozen = {str(path.resolve()): sha(path) for path in files if path.exists()}
  protocol = dict(source=before, environment=runtime_identity(sys.executable), frozen=frozen,
                  scenario='2v1_broad_entropy_high_finisher', schema=14, entropy_coefficient=.025,
                  seed=31415, hidden=64, epochs=4, minibatch=64, rollout=256, cadence=10,
                  episode_limit=256, updates=1024, split=[512, 512], wall_cap_seconds=1800,
                  rss_cap_bytes=512 * 1024 * 1024, output_cap_bytes=512 * 1024 * 1024,
                  scope='Infrastructure/cost pilot only; no validation or confirmation cases.')
  write(out / 'protocol.json', protocol)
  report = dict(passed=False, quality=verified, source_before=before, protocol_sha256=sha(out / 'protocol.json'), commands=[])
  started, resources = time.monotonic(), out / 'resources.jsonl'
  env = dict(os.environ, LD_LIBRARY_PATH=str(build), GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'), GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))

  def run(name, argv):
    begin, peak, reason = time.monotonic(), 0, None
    with (out / (name + '.log')).open('w') as stdout, (out / (name + '.stderr')).open('w') as stderr, resources.open('a') as samples:
      child = subprocess.Popen(list(map(str, argv)), cwd=build, env=env, stdout=stdout, stderr=stderr)
      proc = psutil.Process(child.pid)
      while child.poll() is None:
        try:
          rss = proc.memory_info().rss
          peak = max(peak, rss)
          samples.write(json.dumps(dict(command=name, seconds=time.monotonic()-begin, rss=rss, fds=proc.num_fds())) + '\n')
          samples.flush()
          if rss > protocol['rss_cap_bytes']:
            reason = 'RSS budget'
        except psutil.NoSuchProcess:
          pass
        if time.monotonic() - started > protocol['wall_cap_seconds']:
          reason = 'wall budget'
        if sum(path.stat().st_size for path in out.rglob('*') if path.is_file()) > protocol['output_cap_bytes']:
          reason = 'output budget'
        if reason:
          child.kill()
          child.wait()
          break
        time.sleep(.2)
    row = dict(name=name, argv=list(map(str, argv)), exit_code=child.returncode, seconds=time.monotonic()-begin,
               observed_peak_rss=peak, stdout_sha256=sha(out / (name + '.log')), stderr_sha256=sha(out / (name + '.stderr')))
    report['commands'].append(row)
    assert reason is None and child.returncode == 0, (name, reason, child.returncode)
    return row['seconds']

  try:
    common = [binary, '--scenario', protocol['scenario'], '--seed', protocol['seed'], '--hidden', protocol['hidden'],
              '--epochs', protocol['epochs'], '--minibatch', protocol['minibatch'], '--rollout', protocol['rollout'],
              '--cadence', protocol['cadence'], '--episode-limit', protocol['episode_limit'], '--no-initial-eval']
    full_seconds = run('full1024', [*common, '--updates', 1024, '--eval-episodes', 0,
                                    '--save', out / 'full.fppo', '--export-policy', out / 'full.fpol'])
    run('prefix512', [*common, '--updates', 512, '--eval-episodes', 0, '--save', out / 'prefix.fppo'])
    run('resume512', [*common, '--updates', 512, '--eval-episodes', 0, '--load', out / 'prefix.fppo',
                      '--save', out / 'resumed.fppo', '--export-policy', out / 'resumed.fpol'])
    full, prefix, resumed = [read(out / (name + '.log')) for name in ('full1024', 'prefix512', 'resume512')]
    assert (out / 'full.fppo').read_bytes() == (out / 'resumed.fppo').read_bytes()
    assert (out / 'full.fpol').read_bytes() == (out / 'resumed.fpol').read_bytes()
    assert full['iterations'][:512] == prefix['iterations'] and full['iterations'][512:] == resumed['iterations']
    assert full['version'] == resumed['version'] == 1024 and resumed['start_version'] == 512 and full['total_transitions'] == 262144
    for data in (full, prefix, resumed):
      assert data['scenario'] == protocol['scenario'] and data['ppo']['entropy_coefficient'] == protocol['entropy_coefficient']
      assert data['evaluation']['isolated'] and data['state_before_evaluation_sha256'] == data['state_sha256']
      for row in data['iterations']:
        assert row['learning_rate'] == .0003 * max(.1, 1-(row['version']-1)/8192)
        assert all(math.isfinite(row[key]) for key in ('loss', 'entropy', 'gradient_norm', 'parameter_delta'))
    assert int.from_bytes((out / 'full.fppo').read_bytes()[44:48], 'little') == 14
    run('pilot-holdout-eval', [*common, '--updates', 0, '--load', out / 'full.fppo', '--eval-partition', 'holdout', '--eval-seed', 904730, '--eval-episodes', 64, '--eval-steps', 256])
    evaluation = read(out / 'pilot-holdout-eval.log')
    assert evaluation['evaluation']['isolated'] and evaluation['state_before_evaluation_sha256'] == evaluation['state_sha256']
    assert all(len(next(row['episodes'] for row in evaluation['evaluation']['strategies'] if row['name'] == name)) == 64 for name in ('sample', 'argmax'))
    report.update(passed=True, resume_bytes_equal=True, policy_bytes_equal=True, iterations_equal=True,
                  global_lr_verified=True, checkpoint_sha256=sha(out / 'full.fppo'), policy_sha256=sha(out / 'full.fpol'),
                  full_seconds=full_seconds, projected8192_seconds=full_seconds * 8, transitions_per_second=262144 / full_seconds)
  except BaseException as error:
    report['error'] = f'{type(error).__name__}: {error}'
  finally:
    report['source_after'] = source_fingerprint()
    report['total_seconds'] = time.monotonic() - started
    if before != report['source_after'] or any(sha(Path(path)) != digest for path, digest in frozen.items()):
      report.update(passed=False, error='Frozen source or evidence changed')
    if resources.exists():
      report['resources_sha256'] = sha(resources)
    write(out / 'report.json', report)
  print(json.dumps({key: report.get(key) for key in ('passed', 'full_seconds', 'projected8192_seconds', 'error')}), flush=True)
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
