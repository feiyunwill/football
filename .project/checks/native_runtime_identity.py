"""Record the actual native libraries exercised by a regression probe."""
import hashlib
import importlib
import importlib.metadata
# 2026-09-13: loaded-object verification is available through Linux process mappings.
# import os
import os
import sys
from pathlib import Path


def native_runtime_identity(root):
    import gfootball
    import gfootball_engine
    native = importlib.import_module(gfootball_engine.GameEnv.__module__)
    loader = Path(gfootball_engine.__file__).resolve()
    binding = Path(native.__file__).resolve()
    # 2026-09-13: LD_LIBRARY_PATH may select a different core; identify the actually mapped object.
    # candidates = [loader.parent / name for name in
    #               ('libfootball_engine.so', 'libfootball_engine.dylib', 'football_engine.dll')]
    # cores = [p for p in candidates if p.is_file()]
    # if len(cores) != 1:
    #     raise RuntimeError('Native runtime must have exactly one shared engine library')
    if sys.platform == 'linux':
        from gfootball.frame_sync.match_identity import loaded_native_files
        # This parser verifies mapped device/inode, rejects deleted/ambiguous
        # libraries and also requires the actual binding mapping to be present.
        mapped = loaded_native_files(binding)
        cores = [path for _, path in mapped if path.name == 'libfootball_engine.so'
                 or path.name.startswith('libfootball_engine.so.')]
        resolution = 'linux-verified-process-mapping'
    else:
        candidates = [loader.parent / name for name in
                      ('libfootball_engine.so', 'libfootball_engine.dylib', 'football_engine.dll')]
        cores = [p for p in candidates if p.is_file()]
        resolution = 'package-file-only'
    if len(cores) != 1:
        raise RuntimeError('Native runtime must have exactly one shared engine library')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if sha(loader) != sha(Path(root) / 'engine/__init__.py'):
        raise RuntimeError('Loaded native package initializer differs from the checkout')
    versions = {}
    for name in ('gfootball', 'gymnasium', 'numpy', 'opencv-python', 'pygame-ce', 'six'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return dict(python_package=str(Path(gfootball.__file__).resolve()),
                native_module=native.__name__, loader=str(loader), loader_sha256=sha(loader),
                binding=str(binding), binding_sha256=sha(binding),
                # 2026-09-13: distinguish verified mappings from non-Linux package-file observations.
                # engine=str(cores[0]), engine_sha256=sha(cores[0]),
                engine=str(cores[0]), engine_sha256=sha(cores[0]), engine_resolution=resolution,
                versions=versions, data_dir=os.environ.get('GFOOTBALL_DATA_DIR'),
                font=os.environ.get('GFOOTBALL_FONT'))
