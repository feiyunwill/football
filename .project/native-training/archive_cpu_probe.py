#!/usr/bin/env python3
"""Preserve textual gprofng evidence from an existing experiment (no recollection)."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--experiment', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
report = {'experiment':args.experiment, 'commands':[]}
for name, options in [('functions', ['-limit', '40', '-functions']), ('statistics', ['-statistics', '-overview'])]:
  command = ['gprofng', 'display', 'text', *options, args.experiment]
  result = subprocess.run(command, capture_output=True)
  (args.output / (name + '.log')).write_bytes(result.stdout + result.stderr)
  report['commands'].append({'argv':command, 'exit_code':result.returncode,
                            'sha256':hashlib.sha256(result.stdout + result.stderr).hexdigest()})
  if result.returncode: raise RuntimeError('gprofng display failed')
(args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
