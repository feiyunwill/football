"""Bounded build/content identities for persisted headless match snapshots.

Compatibility is separate from file integrity and is not authentication of an
untrusted native snapshot. Custom engine factories must explicitly implement
get_snapshot_identity(); no type-name or unknown-backend fallback is accepted.
"""
import hashlib
import os
from pathlib import Path
import stat
import struct
import sys
import threading

from gfootball.frame_sync.save_data import SaveFormatError
from gfootball.frame_sync.match_cadence import MATCH_CADENCE

MAX_ENTRIES = 8192
MAX_DIRECTORIES = 512
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
READ_BYTES = 65536
IDENTITY_FIELDS = {'backend', 'abi', 'implementation', 'resources'}
# GameEnv::Initialize uses GFOOTBALL_FONT instead of this fallback when set.
# The explicit font is fingerprinted separately; no other resource is omitted.
UNUSED_FONT_FALLBACK = 'data/media/fonts/alegreya/AlegreyaSansSC-ExtraBold.ttf'


def validate_identity(value):
  if type(value) is not dict or set(value) != IDENTITY_FIELDS:
    raise SaveFormatError('Missing or invalid snapshot compatibility identity')
  for key in ('backend', 'abi'):
    item = value[key]
    if (type(item) is not str or not 1 <= len(item) <= 128
        or any(ord(char) < 32 or ord(char) > 126 for char in item)):
      raise SaveFormatError('Invalid snapshot backend or ABI')
  for key in ('implementation', 'resources'):
    item = value[key]
    if type(item) is not str or len(item) != 64 or any(char not in '0123456789abcdef' for char in item):
      raise SaveFormatError('Invalid snapshot implementation or resource digest')
  return dict(value)


def engine_identity(env):
  provider = getattr(env, 'get_snapshot_identity', None)
  if not callable(provider):
    raise SaveFormatError('Engine must explicitly provide snapshot compatibility identity')
  return validate_identity(provider())


def require_identity(env, expected):
  expected = validate_identity(expected)
  actual = engine_identity(env)
  different = [key for key in sorted(IDENTITY_FIELDS) if actual[key] != expected[key]]
  if different:
    raise SaveFormatError('Snapshot incompatible with current engine: ' + ', '.join(different))


def _stamp(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _reparse(info):
  return bool(getattr(info, 'st_file_attributes', 0) & 0x400)


# 2026-09-10: explicitly configured resources can replace one named fallback.
# def fingerprint(files=(), trees=()):
def fingerprint(files=(), trees=(), *, excluded=()):
  """Hash named files and trees with bounded traversal and 64 KiB reads.

  Tree tuples are (logical name, root, python_only). Absolute installation paths
  are excluded from the digest. Entries below roots cannot be symbolic links.
  Before/after metadata checks reject files or directories changed during reads.
  """
  if type(files) not in (list, tuple) or type(trees) not in (list, tuple) or len(files) > 32 or len(trees) > 8:
    raise SaveFormatError('Fingerprint root capacity exceeded')
  if (type(excluded) not in (list, tuple) or len(excluded) > 8
      or any(type(name) is not str or not 1 <= len(name) <= 512 for name in excluded)):
    raise SaveFormatError('Invalid explicit fingerprint exclusions')
  rows, directories, names = [], [], set()
  entries = total = 0

  def add(name, path):
    nonlocal total
    encoded = name.encode('utf-8')
    if not 1 <= len(encoded) <= 512 or name in names:
      raise SaveFormatError('Invalid or duplicate fingerprint path')
    info = path.lstat()
    # 2026-09-10: Windows junction/reparse entries must not bypass link rejection.
    # if not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= MAX_FILE_BYTES:
    if _reparse(info) or not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= MAX_FILE_BYTES:
      raise SaveFormatError('Fingerprint requires bounded regular files')
    total += info.st_size
    if total > MAX_TOTAL_BYTES or len(rows) >= MAX_ENTRIES:
      raise SaveFormatError('Fingerprint byte or file capacity exceeded')
    names.add(name)
    rows.append((encoded, path, _stamp(info)))

  try:
    for name, filename in files:
      add(name, Path(filename))
    for prefix, root, python_only in trees:
      root = Path(root).resolve(strict=True)
      pending = [(root, '', 0)]
      while pending:
        directory, relative, depth = pending.pop()
        if depth > 16 or len(directories) >= MAX_DIRECTORIES:
          raise SaveFormatError('Fingerprint directory capacity exceeded')
        before = directory.lstat()
        # 2026-09-10: reject directory reparse points as well as POSIX links.
        # if not stat.S_ISDIR(before.st_mode):
        if _reparse(before) or not stat.S_ISDIR(before.st_mode):
          raise SaveFormatError('Fingerprint requires directories without symbolic links')
        directories.append((directory, _stamp(before)))
        with os.scandir(directory) as children:
          for entry in children:
            entries += 1
            if entries > MAX_ENTRIES:
              raise SaveFormatError('Fingerprint entry capacity exceeded')
            if python_only and entry.name == '__pycache__':
              continue
            child_relative = relative + entry.name
            name = prefix + '/' + child_relative
            if len(name.encode('utf-8')) > 512:
              raise SaveFormatError('Fingerprint path capacity exceeded')
            if name in excluded:
              continue
            # 2026-09-10: junctions are not reported as symbolic links on Windows.
            # if entry.is_symlink():
            if entry.is_symlink() or _reparse(entry.stat(follow_symlinks=False)):
              raise SaveFormatError('Fingerprint tree contains a symbolic link')
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
              if len(pending) + len(directories) >= MAX_DIRECTORIES:
                raise SaveFormatError('Fingerprint directory capacity exceeded')
              pending.append((path, child_relative + '/', depth + 1))
            elif not python_only or path.suffix == '.py':
              add(name, path)
    if not rows:
      raise SaveFormatError('Fingerprint has no files')
    digest = hashlib.sha256(b'football.snapshot.files.v1\0')
    for name, path, before in sorted(rows):
      flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
      flags |= getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_CLOEXEC', 0)
      descriptor = os.open(path, flags)
      try:
        # 2026-09-10: Windows path stat and fstat may expose different ctimes.
        # Compare shared identity fields across APIs, ctime within each API.
        # if _stamp(os.fstat(descriptor)) != before:
        opened = _stamp(os.fstat(descriptor))
        if opened[:5] != before[:5]:
          raise SaveFormatError('Fingerprint file changed before reading')
        digest.update(struct.pack('<I', len(name)))
        digest.update(name)
        digest.update(struct.pack('<Q', before[3]))
        remaining = before[3]
        while remaining:
          chunk = os.read(descriptor, min(READ_BYTES, remaining))
          if not chunk:
            raise SaveFormatError('Fingerprint file shortened while reading')
          digest.update(chunk)
          remaining -= len(chunk)
        # 2026-09-10: retain descriptor ctime drift detection against its own origin.
        # if os.read(descriptor, 1) or _stamp(os.fstat(descriptor)) != before:
        if os.read(descriptor, 1) or _stamp(os.fstat(descriptor)) != opened:
          raise SaveFormatError('Fingerprint file changed while reading')
      finally:
        os.close(descriptor)
    for _, path, before in rows:
      if _stamp(path.lstat()) != before:
        raise SaveFormatError('Fingerprint file changed during capture')
    for path, before in directories:
      if _stamp(path.lstat()) != before:
        raise SaveFormatError('Fingerprint directory changed during capture')
    return digest.hexdigest()
  except OSError as error:
    raise SaveFormatError('Cannot read snapshot compatibility files') from error


def parse_native_mapping(line):
  """Parse one bounded proc-maps record; no filesystem or native engine access."""
  if type(line) is not bytes or len(line) > 8192 or b'\0' in line:
    raise SaveFormatError('Invalid native mapping record')
  fields = line.rstrip(b'\n').split(None, 5)
  if len(fields) != 6 or not fields[5].startswith(b'/'):
    return None
  filename = os.fsdecode(fields[5])
  basename = filename.rsplit('/', 1)[-1]
  prefixes = ('libfootball_engine.so', 'libgamelib.so', 'libmenulib.so', 'libdatalib.so', 'libblunted2.so')
  if not (basename.startswith('_gameplayfootball.') or any(
      basename == prefix or basename.startswith(prefix + '.') or basename.startswith(prefix + ' (') for prefix in prefixes)):
    return None
  if filename.endswith(' (deleted)') or '\\' in filename:
    raise SaveFormatError('Native mapped binary was removed or has an unsupported path')
  try:
    major, minor = (int(value, 16) for value in fields[3].split(b':'))
    inode = int(fields[4])
  except ValueError as error:
    raise SaveFormatError('Invalid native mapping device or inode') from error
  if not 0 <= major <= 0xffffffff or not 0 <= minor <= 0xffffffff or not 1 <= inode <= 0xffffffffffffffff:
    raise SaveFormatError('Native mapping identity is out of range')
  return basename, filename, major, minor, inode


def loaded_native_files(module_path, maps_path='/proc/self/maps'):
  """Resolve actually mapped Linux project libraries, including the core .so.

  maps_path is a parser test seam; production always reads this process's maps.
  The mapped inode/device must still match the file being fingerprinted.
  """
  binding = Path(module_path).resolve(strict=True)
  found, consumed = {}, 0
  core_found = binding_found = False
  # 2026-09-10: moved the library selection into parse_native_mapping.
  # prefixes = ('libfootball_engine.so', 'libgamelib.so', 'libmenulib.so', 'libdatalib.so', 'libblunted2.so')
  try:
    with open(maps_path, 'rb') as stream:
      for _ in range(65536):
        line = stream.readline(8193)
        if not line:
          break
        consumed += len(line)
        if len(line) > 8192 or consumed > 4 * 1024 * 1024:
          raise SaveFormatError('Native mapping capacity exceeded')
        # 2026-09-10: isolate bounded maps parsing for portable fixture verification.
        # fields = line.rstrip(b'\n').split(None, 5)
        # if len(fields) != 6 or not fields[5].startswith(b'/'):
        #   continue
        # filename = os.fsdecode(fields[5])
        # basename = filename.rsplit('/', 1)[-1]
        # relevant = basename.startswith('_gameplayfootball.') or any(
        #     basename == prefix or basename.startswith(prefix + '.') or basename.startswith(prefix + ' (') for prefix in prefixes)
        # if not relevant:
        #   continue
        # if filename.endswith(' (deleted)') or '\\' in filename:
        #   raise SaveFormatError('Native mapped binary was removed or has an unsupported path')
        # path = Path(filename).resolve(strict=True)
        # info = path.stat()
        # major, minor = (int(value, 16) for value in fields[3].split(b':'))
        # if (info.st_ino != int(fields[4]) or os.major(info.st_dev) != major or os.minor(info.st_dev) != minor):
        #   raise SaveFormatError('Native mapped binary differs from its file')
        record = parse_native_mapping(line)
        if record is None:
          continue
        basename, filename, major, minor, inode = record
        path = Path(filename).resolve(strict=True)
        info = path.stat()
        if (info.st_ino != inode or os.major(info.st_dev) != major or os.minor(info.st_dev) != minor):
          raise SaveFormatError('Native mapped binary differs from its file')
        if basename in found and found[basename] != path:
          raise SaveFormatError('Ambiguous native library mapping')
        found[basename] = path
        binding_found |= path == binding
        core_found |= basename == 'libfootball_engine.so' or basename.startswith('libfootball_engine.so.')
      else:
        raise SaveFormatError('Native mapping row capacity exceeded')
  except SaveFormatError:
    raise
  except (OSError, ValueError) as error:
    raise SaveFormatError('Cannot identify loaded native libraries') from error
  if not binding_found or not core_found or len(found) > 16:
    raise SaveFormatError('Loaded Python binding and football engine core are both required')
  return [('binary/' + name, path) for name, path in sorted(found.items())]


class NativeMatchEngine:
  """Owner-bound GameEnv adapter with immutable construction identity.

  Identity reads rehash files only at archive/restore boundaries, never on step.
  Changes after engine creation fail closed instead of relabeling loaded assets.
  """
  # 2026-09-10: immutable presentation role; physics identity is shared.
  # def __init__(self, env, identity_provider, initial_identity):
  def __init__(self, env, identity_provider, initial_identity, *, rendering=False):
    if type(rendering) is not bool:
      raise ValueError('Expected a rendering flag')
    self._rendering = rendering
    self._env, self._provider = env, identity_provider
    self._identity = validate_identity(initial_identity)
    self._owner, self._pid = threading.current_thread(), os.getpid()

  def __getattr__(self, name):
    return getattr(self._env, name)

  # 2026-09-10: validate immutable configuration on every step without file I/O.
  # def get_snapshot_identity(self):
  def _check_configuration(self):
    if threading.current_thread() is not self._owner or os.getpid() != self._pid:
      raise RuntimeError('Snapshot identity must stay on its engine owner')
    config = self._env.game_config
    # 2026-09-10: validate the role chosen before construction, including display copies.
    # if (config.render or config.physics_steps_per_frame != 10
    # 2026-09-10: shared cadence is also checked immediately before simulation.
    # if (config.render != self._rendering or config.physics_steps_per_frame != 10
    if (config.render != self._rendering or config.physics_steps_per_frame != MATCH_CADENCE.physics_steps
        or config.render_resolution_x != 1280 or config.render_resolution_y != 720):
      raise SaveFormatError('Snapshot engine configuration changed')

  def step_with_input(self, data):
    self._check_configuration()
    return self._env.step_with_input(data)

  def get_snapshot_identity(self):
    self._check_configuration()
    current = validate_identity(self._provider())
    if current != self._identity:
      raise SaveFormatError('Snapshot implementation or resources changed after engine creation')
    return dict(current)


def native_match_engine(settings):
  return _native_match_engine(settings)


def native_match_display(settings, expected_identity):
  """Fresh rendering lease; identical physics and lifecycle snapshot format."""
  return _native_match_engine(settings, rendering=True,
                              expected_identity=validate_identity(expected_identity))


# 2026-09-10: use the same identified initializer for logic and display roles.
# def native_match_engine(settings):
def _native_match_engine(settings, *, rendering=False, expected_identity=None):
  # Import the actual extension, without replacing missing native dependencies.
  import gfootball_engine
  # 2026-09-10: reserve once before identity I/O and native construction.
  # from gfootball.frame_sync.server_runtime import native_engine
  from gfootball.frame_sync.server_runtime import _initialize_native_engine, ServerSettings
  from gfootball.engine_pool import EngineKey
  from gfootball.owned_engine import create_owned_engine
  from gfootball.frame_sync.match_lifecycle import MatchLifecycleEngine
  if not isinstance(settings, ServerSettings):
    raise ValueError('Expected ServerSettings')
  if sys.platform != 'linux' or sys.byteorder != 'little' or struct.calcsize('P') != 8:
    raise SaveFormatError('Native match archives currently require little-endian Linux 64-bit')
  module = sys.modules.get('_gameplayfootball')
  if module is None or type(gfootball_engine.GameEnv) is not type(module.GameEnv) or gfootball_engine.GameEnv is not module.GameEnv:
    raise SaveFormatError('Cannot identify the actual GameEnv binding')
  package = Path(__file__).resolve().parents[1]
  data = os.environ.get('GFOOTBALL_DATA_DIR')
  font = os.environ.get('GFOOTBALL_FONT')
  if not data or not font:
    raise SaveFormatError('Explicit native data and font paths are required')

  def identity():
    if data != os.environ.get('GFOOTBALL_DATA_DIR') or font != os.environ.get('GFOOTBALL_FONT'):
      raise SaveFormatError('Native resource configuration changed after engine creation')
    binaries = loaded_native_files(module.__file__)
    implementation = fingerprint(binaries + [('policy/server.py', package / 'frame_sync/server.py'),
        ('policy/server_runtime.py', package / 'frame_sync/server_runtime.py'),
        ('policy/engine_pool.py', package / 'engine_pool.py'),
        ('policy/owned_engine.py', package / 'owned_engine.py'),
        ('policy/match_lifecycle.py', package / 'frame_sync/match_lifecycle.py'),
        ('policy/match_cadence.py', package / 'frame_sync/match_cadence.py'),
        ('policy/match_identity.py', Path(__file__))], [('env', package / 'env', True),
                                                       ('scenarios', package / 'scenarios', True)])
    # 2026-09-10: hash the actually configured font, not its unused fallback link.
    # resources = fingerprint([('font', Path(font))], [('data', Path(data), False)])
    resources = fingerprint([('font', Path(font))], [('data', Path(data), False)],
                            excluded=(UNUSED_FONT_FALLBACK,))
    # 2026-09-10: identify the lifecycle envelope in addition to the native ABI.
    # return dict(backend='gfootball.GameEnv.FSTA2.headless10',
    # 2026-09-10: rendering is a resource role, not a different physics format.
    # return dict(backend='gfootball.GameEnv.FSTA2.match1.headless10',
    # 2026-09-13: reject old native snapshots rather than reinterpret frame duration.
    # return dict(backend='gfootball.GameEnv.FSTA2.match1.physics10',
    return dict(backend='gfootball.GameEnv.FSTA2.match1.physics2.cadence50',
        abi='linux-little-p64-' + sys.implementation.cache_tag,
        implementation=implementation, resources=resources)

  # 2026-09-10: reject saturation before hashing ~91MB; do not reserve twice.
  # initial = identity()
  # env = native_engine(settings)
  # try:
  #   result = NativeMatchEngine(env, identity, initial)
  #   result.get_snapshot_identity()
  #   return result
  # except BaseException:
  #   env.close()
  #   raise
  key = EngineKey.current(1280, 720)

  def initialize_identified():
    initial = identity()
    if expected_identity is not None and initial != expected_identity:
      raise SaveFormatError('Display snapshot incompatible with current engine')
    # 2026-09-10: acquire the rendering role before native construction.
    # env = _initialize_native_engine(settings, key)
    # 2026-09-13: logic and display get identical step count and scaled scenario duration.
    # env = (_initialize_native_engine(settings, key, rendering=True) if rendering
    #        else _initialize_native_engine(settings, key))
    env = _initialize_native_engine(settings, key, rendering=rendering,
                                    match_cadence=MATCH_CADENCE)
    try:
      # 2026-09-10: snapshot the termination policy together with native state.
      # result = NativeMatchEngine(env, identity, initial)
      lifecycle = MatchLifecycleEngine(env, normal_mode=int(gfootball_engine.e_GameMode.e_GameMode_Normal),
                                       done_state=gfootball_engine.GameState.game_done)
      # 2026-09-10: preserve role verification on subsequent identity reads.
      # result = NativeMatchEngine(lifecycle, identity, initial)
      result = NativeMatchEngine(lifecycle, identity, initial, rendering=rendering)
      result.get_snapshot_identity()
      return result
    except BaseException as error:
      try:
        env.close()
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Native identity failure cleanup also failed.')
      raise

  # 2026-09-10: display copies count against the shared single-renderer limit.
  # return create_owned_engine(key, initialize_identified)
  return create_owned_engine(key, initialize_identified, rendering=rendering)
