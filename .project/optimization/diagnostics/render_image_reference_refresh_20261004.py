#!/usr/bin/env python3
"""Version reviewed bilinear-Bloom llvmpipe images without replacing the old oracle."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / '.project/checks/golden/render_images_llvmpipe.json'
NEW = ROOT / '.project/checks/golden/render_images_llvmpipe_bilinear_20261004.json'
ARCHIVE = ROOT / '.project/optimization/evidence/render_images_bilinear_20261004.tar.gz'
OLD_SHA256 = 'fe0aa64d30a9157ccb4469471e98ee6f16db49407d61ce1a420fce71d84307be'
SOURCE_COMMIT = 'eae9a2808dd01a9f5a617564d568965f32261a67'
CHANGED = {'bloom': {80, 120, 160}, 'auto_combined': {80, 120, 160}}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pack(entries: dict[str, bytes]) -> bytes:
    items = {'manifest.json': json.dumps({
        'format': 'render-images-bilinear-oracle-v1',
        'files': {key: digest(value) for key, value in sorted(entries.items())},
    }, sort_keys=True, indent=2).encode() + b'\n', **entries}
    stream = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as tar:
            for name, data in sorted(items.items()):
                member = tarfile.TarInfo(name)
                member.size, member.mode, member.mtime = len(data), 0o644, 0
                tar.addfile(member, io.BytesIO(data))
    return stream.getvalue()


def changed_pixels(old: bytes, new: bytes) -> tuple[int, int]:
    if len(old) != len(new) or len(old) % 3:
        raise RuntimeError('RGB sizes differ')
    changed = sum(old[i:i+3] != new[i:i+3] for i in range(0, len(old), 3))
    maximum = max(abs(a-b) for a, b in zip(old, new))
    return changed, maximum


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', type=Path)
    args = parser.parse_args()
    stage = args.stage.resolve()
    if NEW.exists() or ARCHIVE.exists():
        raise RuntimeError('Versioned bilinear reference already exists')
    if digest(OLD.read_bytes()) != OLD_SHA256:
        raise RuntimeError('Historical image oracle changed')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                      text=True).strip()
    if commit != SOURCE_COMMIT or subprocess.run(
            ['git', 'diff', '--quiet', 'HEAD', '--', 'engine/src', 'engine/data'],
            cwd=ROOT).returncode:
        raise RuntimeError('Engine or shader differs from reviewed capture')
    old = json.loads(OLD.read_text())
    capture = stage / 'release'
    build = stage / 'build/release'
    executable = build / 'bin/engine_frame_capture_contract'
    core = build / 'libfootball_engine.so'
    if not executable.is_file() or not core.is_file():
        raise RuntimeError('Release capture binaries missing')
    previous = ROOT / '.project/optimization/benchmarks/render-images-1791078612544601244/release'
    if not previous.is_dir():
        raise RuntimeError('Previous complete image capture missing')
    output = stage / 'bilinear-independent-repeat'
    output.mkdir(exist_ok=False)
    entries: dict[str, bytes] = {}
    differences: dict[str, dict[str, dict[str, int]]] = {}
    current = copy.deepcopy(old)
    for case in old['cases']:
        identity = json.loads((capture / case / 'identity.json').read_text())
        if identity != old['identity']:
            raise RuntimeError(f'Renderer identity changed: {case}')
        differences[case] = {}
        for frame in old['frames']:
            name = f'frame-{frame}'
            current_rgb = (capture / case / f'{name}.rgb').read_bytes()
            prior_rgb = (previous / case / f'{name}.rgb').read_bytes()
            current_state = (capture / case / f'{name}.state').read_bytes()
            prior_state = (previous / case / f'{name}.state').read_bytes()
            if current_state != prior_state or digest(current_state) != old['states'][str(frame)]:
                raise RuntimeError(f'Simulation changed: {case}/{frame}')
            if digest(prior_rgb) != old['cases'][case][str(frame)]:
                raise RuntimeError(f'Previous image differs from old golden: {case}/{frame}')
            changed, maximum = changed_pixels(prior_rgb, current_rgb)
            expected_change = frame in CHANGED.get(case, set())
            if expected_change:
                if not 0 < changed <= 300 or maximum > 7:
                    raise RuntimeError(f'Bilinear image delta exceeds review: {case}/{frame}')
            elif changed:
                raise RuntimeError(f'Unrelated image changed: {case}/{frame}')
            differences[case][str(frame)] = {'changed_pixels': changed,
                                             'max_channel_delta': maximum}
            current['cases'][case][str(frame)] = digest(current_rgb)
            if case in CHANGED:
                entries[f'capture/{case}/{name}.rgb'] = current_rgb
                entries[f'capture/{case}/{name}.state'] = current_state
    for case in CHANGED:
        target = output / case
        environment = dict(os.environ)
        for key in ('LD_PRELOAD', 'DISPLAY', 'SDL_VIDEODRIVER',
                    'GFOOTBALL_PBR_EXPOSURE', 'GFOOTBALL_PBR_AUTO_EXPOSURE',
                    'GFOOTBALL_PBR_BLOOM', 'GFOOTBALL_PBR_FXAA'):
            environment.pop(key, None)
        environment.update({'GFOOTBALL_DATA_DIR': str(ROOT / 'engine/data'),
                            'LIBGL_ALWAYS_SOFTWARE': '1',
                            'LD_LIBRARY_PATH': str(build),
                            'GFOOTBALL_USE_PBR': '1',
                            'GFOOTBALL_PBR_BLOOM': '1'})
        if case == 'auto_combined':
            environment.update({'GFOOTBALL_PBR_FXAA': '1',
                                'GFOOTBALL_PBR_AUTO_EXPOSURE': '1'})
        result = subprocess.run([str(executable), str(target)], cwd=ROOT,
                                env=environment, capture_output=True, timeout=300)
        entries[f'repeat/{case}/process.log'] = (
            f'exit={result.returncode}\n'.encode() + result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'Independent capture failed: {case}')
        if json.loads((target / 'identity.json').read_text()) != old['identity']:
            raise RuntimeError(f'Independent renderer changed: {case}')
        for frame in old['frames']:
            name = f'frame-{frame}'
            for suffix in ('rgb', 'state'):
                actual = (target / f'{name}.{suffix}').read_bytes()
                original = (capture / case / f'{name}.{suffix}').read_bytes()
                if actual != original:
                    raise RuntimeError(f'Independent capture differs: {case}/{name}.{suffix}')
                entries[f'repeat/{case}/{name}.{suffix}'] = actual
    entries['differences.json'] = json.dumps(differences, sort_keys=True, indent=2).encode() + b'\n'
    entries['blur.frag'] = (ROOT / 'engine/data/media/shaders/blur.frag').read_bytes()
    archive = pack(entries)
    current.update({
        'reference_check': 'render_images',
        'reference_stage': stage.name,
        'reference_commit': SOURCE_COMMIT,
        'parent_golden': OLD.relative_to(ROOT).as_posix(),
        'parent_golden_sha256': OLD_SHA256,
        'bilinear_archive': ARCHIVE.relative_to(ROOT).as_posix(),
        'bilinear_archive_sha256': digest(archive),
        'bilinear_generator_sha256': digest(Path(__file__).read_bytes()),
        'blur_shader_sha256': digest(entries['blur.frag']),
        'reference_note': 'Only Bloom and combined frames 80/120/160 change; two independent Release captures match, with unchanged simulation states.',
    })
    ARCHIVE.write_bytes(archive)
    NEW.write_text(json.dumps(current, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'golden': NEW.relative_to(ROOT).as_posix(),
                      'golden_sha256': digest(NEW.read_bytes()),
                      'archive_sha256': digest(archive),
                      'differences': differences}, sort_keys=True))


if __name__ == '__main__':
    main()
