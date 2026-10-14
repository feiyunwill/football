#!/usr/bin/env python3
"""Build a relocatable Linux native PPO directory (system libraries still required)."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
  with path.open('rb') as stream:
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source', type=Path, default=ROOT)
  parser.add_argument('--build-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  source, build, output = args.source.resolve(), args.build_root.resolve(), args.output.resolve()
  if platform.system() != 'Linux':
    parser.error('This directory package is validated only on Linux')
  if build == ROOT or ROOT in build.parents or output == ROOT or ROOT in output.parents:
    parser.error('Build and package directories must be outside the working repository')
  if output.exists():
    parser.error('Use a new package output directory')
  subprocess.run(['cmake', '-S', str(source / 'engine'), '-B', str(build),
                  '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_STANDARD=23',
                  '-DBUILD_PYTHON_BINDINGS=OFF',
                  '-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=' + str(build),
                  '-DCMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE=' + str(build),
                  '-DCMAKE_RUNTIME_OUTPUT_DIRECTORY=' + str(build / 'bin'),
                  '-DCMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE=' + str(build / 'bin'),
                  '-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=' + str(build / 'bin')], check=True)
  subprocess.run(['cmake', '--build', str(build), '--target', 'native_ppo_train',
                  '--parallel', '1'], check=True)
  output.mkdir(parents=True)
  (output / 'bin').mkdir()
  shutil.copy2(build / 'bin/native_ppo_train', output / 'bin/native_ppo_train')
  # CMake BUILD_RPATH_USE_ORIGIN resolves this core from bin/../, with no build path.
  shutil.copy2(build / 'libfootball_engine.so', output / 'libfootball_engine.so')
  shutil.copytree(source / 'engine/data', output / 'data')
  shutil.copytree(source / 'third_party/fonts', output / 'fonts')
  shutil.copy2(source / 'LICENSE', output / 'LICENSE')
  launcher = output / 'native_ppo_train'
  launcher.write_text('''#!/bin/sh
set -eu
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export GFOOTBALL_DATA_DIR="${GFOOTBALL_DATA_DIR:-$bundle/data}"
export GFOOTBALL_FONT="${GFOOTBALL_FONT:-$bundle/fonts/AlegreyaSansSC-ExtraBold.ttf}"
exec "$bundle/bin/native_ppo_train" "$@"
''')
  launcher.chmod(0o755)
  (output / 'README.txt').write_text(
      'Run ./native_ppo_train --help or pass training options.\n'
      'Move this whole directory together; resources and the core are included.\n'
      'Requires compatible Linux libc/libstdc++, SDL2/image/ttf/gfx and OpenGL/EGL system libraries.\n'
      'No Python interpreter is needed at runtime. This is not a manylinux/static distribution.\n'
      'FPPO checkpoints require the same source/build/ABI and configuration.\n')
  files = {str(path.relative_to(output)): sha(path) for path in sorted(output.rglob('*')) if path.is_file()}
  (output / 'manifest.json').write_text(json.dumps(dict(schema=1, platform=platform.platform(), files=files), indent=2) + '\n')
  print(json.dumps(dict(package=str(output), files=len(files))))


if __name__ == '__main__':
  main()
