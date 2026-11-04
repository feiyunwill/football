"""Register the Schema14 five-seed budget from its audited bounded pilot."""
import argparse
import json
import math
from pathlib import Path

import quality
from validate import ROOT, sha, source_fingerprint


def read(path):
  return json.loads(path.read_text())


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  for key in ('pilot', 'audit', 'quality', 'output'):
    parser.add_argument('--' + key, type=Path, required=True)
  args = parser.parse_args()
  quality.verify(args.quality / 'report.json')
  source = source_fingerprint()
  pilot, audit, protocol = read(args.pilot / 'report.json'), read(args.audit / 'report.json'), read(args.pilot / 'protocol.json')
  assert pilot['passed'] and audit['passed']
  assert protocol['schema'] == 14 and protocol['scenario'] == '2v1_broad_entropy_high_finisher'
  assert protocol['entropy_coefficient'] == .025
  assert source == pilot['source_before'] == pilot['source_after'] == protocol['source']
  assert source['sha256'] == audit['source_sha256']
  assert sha(args.pilot / 'report.json') == audit['report_sha256']
  assert all(sha(Path(path)) == digest for path, digest in protocol['frozen'].items())
  assert pilot['resume_bytes_equal'] and pilot['policy_bytes_equal'] and pilot['iterations_equal'] and pilot['global_lr_verified']
  projected = pilot['projected8192_seconds']
  per_seed = math.ceil((projected * 1.10 + 180) / 60) * 60
  assert 0 < projected < per_seed <= 3600
  note = ROOT / '.project/optimization/o23-schema14-entropy-high-finisher-budget-20261029.md'
  files = [Path(__file__), args.pilot / 'report.json', args.pilot / 'protocol.json', args.audit / 'report.json', args.quality / 'report.json', note]
  frozen = {str(path.resolve()): sha(path) for path in files}
  receipt = dict(
      passed=True,
      source_sha256=source['sha256'],
      pilot_report_sha256=sha(args.pilot / 'report.json'),
      pilot_audit_sha256=sha(args.audit / 'report.json'),
      projected8192_seconds=projected,
      budget=dict(max_wall_seconds_per_training_run=per_seed, max_total_training_wall_seconds=5 * per_seed,
                  max_child_rss_bytes=512 * 1024**2, max_study_output_bytes=2 * 1024**3),
      frozen=frozen,
      optimizer_updates_per_seed=8192,
      seeds=[42, 123, 2026, 31415, 271828],
      checkpoint_schedule=[1024, 2048, 3072, 4096, 5120, 6144, 7168, 7424, 7680, 7936, 8192],
      acceptance_gates=dict(total=970, seed=180, group=180, passes=40, joint=40),
      confirmation_opened=False)
  args.output.parent.mkdir(parents=True, exist_ok=True)
  with args.output.open('x') as stream:
    stream.write(json.dumps(receipt, indent=2) + '\n')
  print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
  main()
