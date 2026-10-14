#!/usr/bin/env python3
"""Preserve exact staged baseline before building an optimization candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from validate import source_fingerprint
parser = argparse.ArgumentParser()
parser.add_argument('--build-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
source = args.build_root.resolve() / 'validation-stage/gfootball_engine'
target = args.output.resolve() / 'gfootball_engine'
target.mkdir(parents=True, exist_ok=False)
report = {'source':source_fingerprint(), 'artifacts':{}}
for name in ('__init__.py', '_gameplayfootball.so', 'libfootball_engine.so'):
  shutil.copy2(source / name, target / name)
  report['artifacts'][name] = hashlib.sha256((target / name).read_bytes()).hexdigest()
for name in ('data', 'fonts'):
  (target / name).symlink_to((source / name).resolve(), target_is_directory=True)
(target.parent / 'baseline.json').write_text(json.dumps(report, indent=2) + '\n')
