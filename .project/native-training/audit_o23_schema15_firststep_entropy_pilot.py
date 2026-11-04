"""Independently verify the bounded Schema15 first-step-entropy pilot."""
import argparse
import json
import math
import traceback
from pathlib import Path

import quality
from validate import sha, source_fingerprint


def read(path):
  return json.loads(path.read_text())


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--pilot', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  root, out = args.pilot.resolve(), args.output.resolve()
  out.mkdir(parents=True, exist_ok=False)
  result = dict(passed=False)
  try:
    protocol, report = read(root / 'protocol.json'), read(root / 'report.json')
    quality.verify(Path(report['quality']['report']).resolve())
    assert protocol['scenario'] == '2v1_broad_firststep_entropy_finisher'
    assert protocol['schema'] == 15 and protocol['entropy_coefficient'] == .02
    assert protocol['first_step_entropy_multiplier'] == 2.5
    assert protocol['scope'] == 'Infrastructure/cost pilot only; no validation or confirmation cases.'
    assert report['passed'] and report['source_before'] == report['source_after'] == protocol['source'] == source_fingerprint()
    assert sha(root / 'protocol.json') == report['protocol_sha256']
    assert all(sha(Path(path)) == digest for path, digest in protocol['frozen'].items())
    assert len(report['commands']) == 4 and report['total_seconds'] <= protocol['wall_cap_seconds']
    for row in report['commands']:
      assert row['exit_code'] == 0
      assert sha(root / (row['name'] + '.log')) == row['stdout_sha256']
      assert sha(root / (row['name'] + '.stderr')) == row['stderr_sha256']
    full, prefix, resumed = [read(root / (name + '.log')) for name in ('full1024', 'prefix512', 'resume512')]
    assert full['scenario'] == prefix['scenario'] == resumed['scenario'] == protocol['scenario']
    assert full['ppo']['entropy_coefficient'] == prefix['ppo']['entropy_coefficient'] == resumed['ppo']['entropy_coefficient'] == .02
    assert (root / 'full.fppo').read_bytes() == (root / 'resumed.fppo').read_bytes()
    assert (root / 'full.fpol').read_bytes() == (root / 'resumed.fpol').read_bytes()
    assert full['iterations'][:512] == prefix['iterations'] and full['iterations'][512:] == resumed['iterations']
    assert resumed['start_version'] == 512 and full['version'] == resumed['version'] == 1024 and full['total_transitions'] == 262144
    for data in (full, prefix, resumed):
      assert data['evaluation']['isolated'] and data['state_before_evaluation_sha256'] == data['state_sha256']
      for row in data['iterations']:
        assert row['learning_rate'] == .0003 * max(.1, 1-(row['version']-1)/8192)
        assert all(math.isfinite(row[key]) for key in ('loss', 'entropy', 'gradient_norm', 'parameter_delta'))
    checkpoint = root / 'full.fppo'
    assert sha(checkpoint) == report['checkpoint_sha256'] and int.from_bytes(checkpoint.read_bytes()[44:48], 'little') == 15
    assert sha(root / 'full.fpol') == report['policy_sha256']
    evaluation = read(root / 'pilot-holdout-eval.log')
    assert evaluation['evaluation']['isolated'] and evaluation['state_before_evaluation_sha256'] == evaluation['state_sha256']
    assert all(len(next(row['episodes'] for row in evaluation['evaluation']['strategies'] if row['name'] == name)) == 64 for name in ('sample', 'argmax'))
    result.update(passed=True, total_seconds=report['total_seconds'], full_seconds=report['full_seconds'],
                  projected8192_seconds=report['projected8192_seconds'], resume_bytes_equal=True,
                  policy_bytes_equal=True, iterations_equal=True, checkpoint_schema=15,
                  report_sha256=sha(root / 'report.json'), protocol_sha256=sha(root / 'protocol.json'),
                  source_sha256=protocol['source']['sha256'], auditor_sha256=sha(Path(__file__)))
  except BaseException as error:
    result['error'] = f'{type(error).__name__}: {error}\n{traceback.format_exc()}'
  (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
  print(json.dumps(result), flush=True)
  return 0 if result['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
