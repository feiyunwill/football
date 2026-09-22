# 2026-09-09: bounded cross-process directory reservations for recording output.
"""Coordinate cooperating writers with OS locks, not stale PID/timeout guesses.

The fixed control directory is retained to preserve lock-file identity. Up to
16 lock/data slot pairs plus one guard occupy bounded metadata storage. Stale
slots become reusable after process exit; orphan payload files remain accounted
as existing files. No user files are deleted by admission or crash recovery.
"""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time
import uuid
import weakref

# 2026-09-10: file-only save persistence needs no array/codec dependency.
# from gfootball.recording_buffers import RecordingCapacityError
from gfootball.recording_errors import RecordingCapacityError

if os.name == 'nt':
  import msvcrt
else:
  import fcntl

CONTROL_NAME = '.football-recording-v1'
SLOTS = 16
METADATA_BYTES = 4096
MAGIC = b'football-recording-directory-v1\n'
_registry_lock = threading.RLock()
_registry = weakref.WeakValueDictionary()
_lock_descriptors = set()


def _after_fork():
  global _registry_lock, _registry, _lock_descriptors
  # Close the child's inherited references; LOCK_UN would unlock the parent's
  # shared open-file description on POSIX and must not be used here.
  for fd in _lock_descriptors:
    try:
      os.close(fd)
    except OSError:
      pass
  _lock_descriptors = set()
  _registry_lock = threading.RLock()
  _registry = weakref.WeakValueDictionary()


if hasattr(os, 'register_at_fork'):
  os.register_at_fork(after_in_child=_after_fork)


def _regular_fd(path, create=False):
  flags = os.O_RDWR | (os.O_CREAT if create else 0) | getattr(os, 'O_NOFOLLOW', 0)
  fd = os.open(path, flags, 0o600)
  try:
    info, current = os.fstat(fd), path.lstat()
    if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(current.st_mode)
        or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
      raise OSError('Recording control file is not a stable regular file')
    os.set_inheritable(fd, False)
    return fd
  except BaseException:
    os.close(fd)
    raise


def _lock(fd):
  try:
    if os.name == 'nt':
      os.lseek(fd, 0, os.SEEK_SET)
      msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return True
  except OSError as error:
    if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
      return False
    raise


def _close_lock(fd):
  _lock_descriptors.discard(fd)
  os.close(fd)  # All supported locks are released by descriptor close.


def _policy(limits):
  return {name: getattr(limits, name) for name in
          ('total_bytes', 'total_files', 'active_dumps', 'scan_entries')}


def _decode_record(data):
  def unique(pairs):
    result = {}
    for key, value in pairs:
      if key in result:
        raise ValueError('Duplicate recording metadata key')
      result[key] = value
    return result

  record = json.loads(data, object_pairs_hook=unique)
  if type(record) is not dict or set(record) != {'version', 'token', 'bytes', 'files', 'policy', 'paths'}:
    raise ValueError('Invalid recording reservation metadata')
  if (type(record['version']) is not int or record['version'] != 1
      or type(record['token']) is not str or not re.fullmatch('[0-9a-f]{32}', record['token'])
      or type(record['bytes']) is not int or not 128 <= record['bytes'] <= 3 * 1024**3
      or type(record['files']) is not int or not 1 <= record['files'] <= 2):
    raise ValueError('Invalid recording reservation values')
  policy = record['policy']
  bounds = {'total_bytes': (128, 16 * 1024**3), 'total_files': (1, 4096),
            'active_dumps': (1, SLOTS), 'scan_entries': (1, 16384)}
  if type(policy) is not dict or set(policy) != set(bounds):
    raise ValueError('Invalid recording directory policy')
  for name, (minimum, maximum) in bounds.items():
    if type(policy[name]) is not int or not minimum <= policy[name] <= maximum:
      raise ValueError('Invalid recording directory policy bound')
  paths = record['paths']
  if type(paths) is not dict or len(paths) > record['files']:
    raise ValueError('Invalid recording temporary paths')
  pattern = r'\.recording-' + record['token'] + r'-[a-z0-9_]{1,32}\.(dump\.part|avi|webm)'
  for name, identity in paths.items():
    if (not re.fullmatch(pattern, name) or type(identity) is not list or len(identity) != 2
        or any(type(value) is not int or not 0 <= value < 2**128 for value in identity)):
      raise ValueError('Invalid recording temporary file identity')
  return record


class DirectoryLease:
  def __init__(self, directory, slot, fd, record):
    self.directory, self.slot, self.fd, self.record = directory, slot, fd, record
    self.pid = os.getpid()

  def check(self):
    if self.pid != os.getpid():
      raise RuntimeError('Recording reservations cannot be used after fork')
    if self.fd is None:
      raise RuntimeError('Recording reservation is released')

  def __del__(self):
    # A directly acquired lease is still an owning handle if its budget goes
    # away. Closing it reclaims the slot; payload files remain accounted.
    if getattr(self, 'pid', None) == os.getpid() and getattr(self, 'fd', None) is not None:
      fd, self.fd = self.fd, None
      try:
        _close_lock(fd)
      except OSError:
        pass


class DirectoryReservations:
  def __init__(self, directory):
    self.directory = Path(directory).resolve()
    self.control = self.directory / CONTROL_NAME
    self._thread_lock = threading.RLock()
    self._depth = threading.local()
    self.pid = os.getpid()

  def _prepare(self):
    self.directory.mkdir(parents=True, exist_ok=True)
    self.control.mkdir(mode=0o700, exist_ok=True)
    if not stat.S_ISDIR(self.control.lstat().st_mode):
      raise OSError('Recording control directory is not a real directory')
    # Unknown content is preserved and rejected, never recursively removed.
    with os.scandir(self.control) as entries:
      for count, entry in enumerate(entries, 1):
        allowed = entry.name == 'guard' or re.fullmatch(r'slot-(?:[0-9]|1[0-5])\.(?:lock|json)', entry.name)
        info = entry.stat(follow_symlinks=False)
        if count > 2 * SLOTS + 1 or not allowed or not stat.S_ISREG(info.st_mode):
          raise ValueError('Unexpected recording control directory content')
        if info.st_size > METADATA_BYTES:
          raise RecordingCapacityError('Recording control metadata exceeds its byte budget')

  @contextmanager
  def transaction(self):
    if self.pid != os.getpid():
      raise RuntimeError('Recording directory owner cannot be used after fork')
    deadline = time.monotonic() + 2
    if not self._thread_lock.acquire(timeout=2):
      raise TimeoutError('Recording directory is busy')
    fd = None
    depth = getattr(self._depth, 'value', 0)
    try:
      if depth == 0:
        self._prepare()
        fd = _regular_fd(self.control / 'guard', create=True)
        _lock_descriptors.add(fd)
        while not _lock(fd):
          if time.monotonic() >= deadline:
            raise TimeoutError('Recording directory is busy')
          time.sleep(0.005)
        os.lseek(fd, 0, os.SEEK_SET)
        magic = os.read(fd, len(MAGIC) + 1)
        if not magic:
          os.lseek(fd, 0, os.SEEK_SET)
          if os.write(fd, MAGIC) != len(MAGIC):
            raise OSError('Recording directory marker write failed')
        elif magic != MAGIC:
          raise ValueError('Recording directory marker does not match')
      self._depth.value = depth + 1
      yield
    finally:
      self._depth.value = depth
      # 2026-09-09: release the thread lock even if closing a descriptor fails.
      # if fd is not None:
      #   _close_lock(fd)
      # self._thread_lock.release()
      try:
        if fd is not None:
          _close_lock(fd)
      finally:
        self._thread_lock.release()

  def _scan_leases(self):
    active, free = [], []
    for slot in range(SLOTS):
      path = self.control / ('slot-%d.lock' % slot)
      try:
        fd = _regular_fd(path)
      except FileNotFoundError:
        free.append(slot)
        continue
      _lock_descriptors.add(fd)
      try:
        if _lock(fd):
          free.append(slot)
        else:
          data_path = self.control / ('slot-%d.json' % slot)
          metadata = _regular_fd(data_path)
          try:
            data = os.read(metadata, METADATA_BYTES + 1)
          finally:
            os.close(metadata)
          if len(data) > METADATA_BYTES:
            raise RecordingCapacityError('Recording reservation metadata is oversized')
          active.append(_decode_record(data))
      finally:
        # 2026-09-09: fork recovery must also close inherited probe locks.
        # os.close(fd)
        _close_lock(fd)
    return active, free

  def _store(self, lease):
    data = json.dumps(lease.record, sort_keys=True, separators=(',', ':')).encode('ascii')
    if len(data) > METADATA_BYTES:
      raise RecordingCapacityError('Recording reservation metadata is oversized')
    fd = _regular_fd(self.control / ('slot-%d.json' % lease.slot), create=True)
    try:
      os.lseek(fd, 0, os.SEEK_SET)
      remaining = memoryview(data)
      while remaining:
        count = os.write(fd, remaining)
        if count <= 0:
          raise OSError('Recording metadata write made no progress')
        remaining = remaining[count:]
      os.ftruncate(fd, len(data))
    finally:
      os.close(fd)

  def reserve(self, limits, video):
    with self.transaction():
      active, free = self._scan_leases()
      policy = _policy(limits)
      if any(record['policy'] != policy for record in active):
        raise ValueError('Concurrent recording directory policies must match')
      if not free or len(active) >= limits.active_dumps:
        raise RecordingCapacityError('Active directory dump count exceeded')
      owned = {name: tuple(identity) for record in active for name, identity in record['paths'].items()}
      size = sum(record['bytes'] for record in active)
      files = sum(record['files'] for record in active)
      with os.scandir(self.directory) as entries:
        count = 0
        for entry in entries:
          if entry.name == CONTROL_NAME:
            continue
          count += 1
          if count > limits.scan_entries:
            raise RecordingCapacityError('Recording directory scan limit exceeded')
          info = entry.stat(follow_symlinks=False)
          if entry.name in owned:
            # 2026-09-09: Windows DirEntry.stat reports dev/ino as zero on this
            # runtime; use an actual path stat before comparing fd identities.
            info = os.stat(entry.path, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or owned[entry.name] != (info.st_dev, info.st_ino):
              raise OSError('Active recording temporary file changed identity')
          elif stat.S_ISREG(info.st_mode):
            size += info.st_size
            files += 1
          elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('Recording directory contains a non-regular entry')
      requested = limits.dump_bytes + (limits.video_bytes if video else 0)
      file_count = 2 if video else 1
      if size + requested > limits.total_bytes or files + file_count > limits.total_files:
        raise RecordingCapacityError('Recording directory output budget exceeded')
      slot = free[0]
      fd = _regular_fd(self.control / ('slot-%d.lock' % slot), create=True)
      _lock_descriptors.add(fd)
      lease = None
      try:
        if not _lock(fd):
          raise OSError('Recording reservation slot changed while directory was locked')
        record = dict(version=1, token=uuid.uuid4().hex, bytes=requested,
                      files=file_count, policy=policy, paths={})
        lease = DirectoryLease(self, slot, fd, record)
        self._store(lease)
        return lease
      except BaseException:
        # 2026-09-09: an exception traceback may retain the half-built lease.
        # Disarm its destructor before closing, so later fd reuse stays safe.
        if lease is not None:
          lease.fd = None
        _close_lock(fd)
        raise

  def temporary(self, lease, suffix):
    lease.check()
    if lease.directory is not self or suffix not in ('.dump.part', '.avi', '.webm'):
      raise ValueError('Invalid recording temporary request')
    with self.transaction():
      if len(lease.record['paths']) >= lease.record['files']:
        raise RecordingCapacityError('Too many files for recording reservation')
      fd, name = tempfile.mkstemp(prefix='.recording-' + lease.record['token'] + '-',
                                  suffix=suffix, dir=self.directory)
      path = Path(name)
      try:
        info = os.fstat(fd)
        lease.record['paths'][path.name] = [info.st_dev, info.st_ino]
        self._store(lease)
        return fd, path
      except BaseException:
        os.close(fd)
        # Exact freshly-created path, under the directory guard, never recursive.
        path.unlink()
        lease.record['paths'].pop(path.name, None)
        raise

  def release(self, lease):
    lease.check()
    if lease.directory is not self:
      raise ValueError('Recording reservation belongs to another directory')
    # Closing the lease is safe even if a guard/metadata path has become unusable.
    fd, lease.fd = lease.fd, None
    _close_lock(fd)


def directory_reservations(directory):
  # 2026-09-09: preserve actual case for case-sensitive UNC/WSL filesystems.
  # OS locks still coordinate aliases not unified by this process-local cache.
  # key = os.path.normcase(str(Path(directory).resolve()))
  key = str(Path(directory).resolve())
  with _registry_lock:
    value = _registry.get(key)
    if value is None:
      value = DirectoryReservations(key)
      _registry[key] = value
    return value
