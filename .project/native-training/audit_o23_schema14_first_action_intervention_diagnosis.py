"""Independently audit the Schema14 first-action intervention diagnostic receipt."""
import argparse
import json
from pathlib import Path

import quality
from validate import sha, source_fingerprint

SEEDS = (42, 123, 2026, 31415, 271828)
SELECTED = (14, 17, 25, 127, 152, 163, 173, 175, 191, 193, 194)


def read(path):
  return json.loads(path.read_text())


def rows(path):
  return [json.loads(line) for line in path.read_text().splitlines()]


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--diagnostic', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  root, out = args.diagnostic.resolve(), args.output.resolve()
  out.mkdir(parents=True, exist_ok=False)
  result = dict(passed=False)
  try:
    protocol, report = read(root / 'protocol.json'), read(root / 'report.json')
    quality.verify(Path(protocol['quality']['report']).resolve())
    assert report['passed'] and report['source_before'] == report['source_after'] == protocol['source'] == source_fingerprint()
    assert tuple(protocol['selected']) == SELECTED and tuple(protocol['seeds']) == SEEDS and protocol['treatments'] == list(range(19))
    assert protocol['baseline_forced_first_action'] == -1
    assert sha(root / 'protocol.json') == report['protocol_sha256']
    assert all(sha(Path(path)) == digest for path, digest in protocol['frozen'].items())
    study = read(Path(protocol['study']) / 'report.json')
    diagnosis = read(Path(protocol['diagnosis']) / 'report.json')
    assert study['passed'] and study['validation_passed'] is False and diagnosis['passed']
    assert tuple(item['index'] for item in diagnosis['universal_failures']) == SELECTED
    summary = {}
    for seed in SEEDS:
      command = next(item for item in report['commands'] if item['seed'] == seed)
      log, error = root / f'interventions-{seed}.jsonl', root / f'interventions-{seed}.stderr'
      assert command['exit_code'] == 0 and sha(log) == command['stdout_sha256'] and sha(error) == command['stderr_sha256']
      values = rows(log)
      assert len(values) == len(SELECTED) * 20
      by_case = {index: [row for row in values if row['index'] == index] for index in SELECTED}
      assert all(len(cells) == 20 and [row['forced_first_action'] for row in cells] == [-1, *range(19)] for cells in by_case.values())
      assert all(cells[0]['sampled_first_action'] == cells[0]['applied_first_action'] for cells in by_case.values())
      forced = {str(action): sum(cells[action + 1]['score'] > 0 for cells in by_case.values()) for action in range(19)}
      baseline_goals = sum(cells[0]['score'] > 0 for cells in by_case.values())
      expected = dict(baseline_goals=baseline_goals, forced_goals=forced, action_effect_observed=any(forced.values()))
      assert expected == report['summary'][str(seed)]
      summary[str(seed)] = expected
    result.update(passed=True, diagnostic_report_sha256=sha(root / 'report.json'), protocol_sha256=sha(root / 'protocol.json'), source_sha256=protocol['source']['sha256'], summary=summary, hypothesis_falsified=not any(item['action_effect_observed'] for item in summary.values()), auditor_sha256=sha(Path(__file__)))
  except BaseException as error:
    result['error'] = f'{type(error).__name__}: {error}'
  (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
  print(json.dumps({key: result.get(key) for key in ('passed', 'hypothesis_falsified', 'error')}), flush=True)
  return 0 if result['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
