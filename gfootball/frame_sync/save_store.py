"""Checksummed save collections with bounded reads and atomic publication."""
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import stat

from gfootball.recording_directory import directory_reservations
from gfootball.recording_errors import RecordingCapacityError
from gfootball.frame_sync.save_data import (
    SaveCapacityError, SaveConflictError, SaveFormatError, decode_json, integer, slot_from_json,
)


@dataclass(frozen=True)
class SaveDiskLimits:
  total_bytes: int = 64 * 1024**2
  total_files: int = 32
  active_dumps: int = 4
  scan_entries: int = 256
  # Internal reservation amount is replaced with the actual bounded file size.
  dump_bytes: int = 0
  video_bytes: int = 0

  def __post_init__(self):
    for name, low, high in (('total_bytes', 1024, 1024**3), ('total_files', 2, 1024),
                            ('active_dumps', 1, 16), ('scan_entries', 2, 16384)):
      integer(getattr(self, name), name, low, high)
    integer(self.dump_bytes, 'save reservation', 0, 128 * 1024**2)
    if self.video_bytes != 0:
      raise ValueError('Save reservations do not include video')


def _line(value):
  return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')


def _identity(info):
  return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class SaveStore:
  def __init__(self, path, limits, disk_limits=None):
    raw_path = os.fspath(path)
    if type(raw_path) is not str or len(raw_path) > 4096 or not raw_path or '\0' in raw_path:
      raise SaveFormatError('Save path must be a bounded nonempty text path')
    target = Path(raw_path)
    self.path = target.parent.resolve() / target.name
    self.limits = limits
    self.disk_limits = SaveDiskLimits() if disk_limits is None else disk_limits
    if type(self.disk_limits) is not SaveDiskLimits:
      raise TypeError('Expected SaveDiskLimits')
    self.directory = directory_reservations(self.path.parent)
    self.last_publication = None

  def read(self):
    with self.directory.transaction():
      return self._read()

  def _read(self, retain=True):
    try:
      before = self.path.lstat()
    except FileNotFoundError:
      return {}, None
    if not stat.S_ISREG(before.st_mode):
      raise SaveFormatError('Save path must be a regular file, not a link or directory')
    if before.st_size > self.limits.file_bytes:
      raise SaveCapacityError('Save file byte capacity exceeded')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(self.path, flags)
    try:
      stream = os.fdopen(fd, 'rb', buffering=65536)
    except BaseException:
      os.close(fd)
      raise
    with stream:
      actual = os.fstat(stream.fileno())
      # 2026-09-10: Windows path stat and fstat expose different ctime values.
      # Compare identity/size/mtime across APIs, then each ctime against its own
      # source at the end of the read so change detection is retained.
      # if not stat.S_ISREG(actual.st_mode) or _identity(actual) != _identity(before):
      if not stat.S_ISREG(actual.st_mode) or _identity(actual)[:4] != _identity(before)[:4]:
        raise SaveConflictError('Save file changed before reading')
      def read_line(maximum):
        raw = stream.readline(maximum + 1)
        if len(raw) > maximum:
          raise SaveCapacityError('Save file line capacity exceeded')
        if not raw or not raw.endswith(b'\n'):
          raise SaveFormatError('Save file is truncated')
        return raw
      header_raw = read_line(512)
      header = decode_json(header_raw, self.limits, 512)
      if (type(header) is not dict or set(header) != {'format', 'version', 'generation', 'slots'}
          or header['format'] != 'football.save_collection' or type(header['version']) is not int
          or header['version'] != 1):
        raise SaveFormatError('Unsupported save collection header')
      generation = integer(header['generation'], 'save generation', 1)
      count = integer(header['slots'], 'slot count', 0, self.limits.slots)
      digest = hashlib.sha256(header_raw)
      slots, used = {}, 0
      for _ in range(count):
        raw = read_line(self.limits.slot_bytes + 2048)
        digest.update(raw)
        slot = slot_from_json(raw, self.limits)
        if slot.slot_id in slots:
          raise SaveFormatError('Duplicate slot ID in collection')
        used += slot._bytes
        if used > self.limits.total_bytes:
          raise SaveCapacityError('Total retained save capacity exceeded')
        slots[slot.slot_id] = slot if retain else None
      footer = decode_json(read_line(256), self.limits, 256)
      if type(footer) is not dict or set(footer) != {'sha256'} or footer['sha256'] != digest.hexdigest():
        raise SaveFormatError('Save collection checksum mismatch')
      if stream.read(1):
        raise SaveFormatError('Trailing data after save footer')
      # if _identity(os.fstat(stream.fileno())) != _identity(before) or _identity(self.path.lstat()) != _identity(before):
      if _identity(os.fstat(stream.fileno())) != _identity(actual) or _identity(self.path.lstat()) != _identity(before):
        raise SaveConflictError('Save file changed while reading')
      return slots, (generation, digest.hexdigest())

  def write(self, slots, expected_revision):
    """Publish a complete collection or preserve the old collection.

    last_publication is set immediately after rename. A rare failure during
    directory sync/lease release is reported with save_committed=True, allowing
    the manager to keep memory consistent with the already-published file.
    """
    self.last_publication = None
    try:
      return self._write(slots, expected_revision)
    except BaseException as error:
      # Include failure while releasing the outer directory guard as well.
      if self.last_publication is not None:
        error.save_committed = True
        if hasattr(error, 'add_note'):
          error.add_note('The save was published; final synchronization or cleanup reported an error.')
      raise

  def _write(self, slots, expected_revision):
    with self.directory.transaction():
      _, revision = self._read(retain=False)
      if revision != expected_revision:
        raise SaveConflictError('Save collection changed; reload before writing')
      generation = integer(1 if revision is None else revision[0] + 1, 'save generation', 1)
      entries = tuple(slots[key] for key in sorted(slots))
      integer(len(entries), 'slot count', 0, self.limits.slots)
      if sum(slot._bytes for slot in entries) > self.limits.total_bytes:
        raise SaveCapacityError('Total retained save capacity exceeded')
      header = _line(dict(format='football.save_collection', version=1, generation=generation, slots=len(entries)))
      digest = hashlib.sha256(header)
      size = len(header)
      for slot in entries:
        raw = slot.export_bytes() + b'\n'
        digest.update(raw)
        size += len(raw)
      footer = _line(dict(sha256=digest.hexdigest()))
      size += len(footer)
      if size > self.limits.file_bytes:
        raise SaveCapacityError('Save file byte capacity exceeded')
      new_revision = generation, digest.hexdigest()
      try:
        lease = self.directory.reserve(replace(self.disk_limits, dump_bytes=size), False)
      except RecordingCapacityError as error:
        raise SaveCapacityError(str(error)) from error
      temporary = identity = stream = None
      error = None
      try:
        fd, temporary = self.directory.temporary(lease, '.dump.part')
        try:
          info = os.fstat(fd)
          identity = info.st_dev, info.st_ino
          stream = os.fdopen(fd, 'wb', buffering=65536)
        except BaseException:
          os.close(fd)
          raise
        written = 0
        def write(raw):
          nonlocal written
          if written + len(raw) > size:
            raise SaveCapacityError('Save output exceeded its reservation')
          if stream.write(raw) != len(raw):
            raise OSError('Short save write')
          written += len(raw)
        write(header)
        for slot in entries:
          write(slot.export_bytes() + b'\n')
        write(footer)
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        stream = None
        # Recheck the exact opened target against a non-cooperating modification.
        _, current_revision = self._read(retain=False)
        if current_revision != expected_revision:
          raise SaveConflictError('Save collection changed during writing')
        os.replace(temporary, self.path)
        temporary = None
        self.last_publication = new_revision
        if os.name != 'nt':
          directory_fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
          try:
            os.fsync(directory_fd)
          finally:
            os.close(directory_fd)
      except BaseException as failure:
        error = failure
      finally:
        try:
          if stream is not None:
            stream.close()
        except BaseException as failure:
          error = error or failure
        try:
          if temporary is not None and identity is not None:
            info = temporary.lstat()
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != identity:
              raise SaveConflictError('Save temporary path changed identity; preserved')
            temporary.unlink()
        except BaseException as failure:
          error = error or failure
        try:
          self.directory.release(lease)
        except BaseException as failure:
          error = error or failure
      if error is not None:
        raise error
      return new_revision
