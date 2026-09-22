# 2026-09-09: bounded, explicitly closed recording files without Gym imports.
"""OS-coordinated recording reservations and transactional file publication.

Directory totals include direct regular files, including previous runs.
Cooperating processes share bounded OS-locked directory reservations. Video size is checked after each encoder write
and release: encoder buffers and one-write temporary overshoot are not a hard
disk/RSS budget. Publication requires same-filesystem hard links and never
overwrites an existing destination. A dump/video pair is not an atomic group.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import math
import os
from pathlib import Path
import pickle
import re
import stat
import tempfile
import threading

import cv2
import numpy as np

from gfootball.recording_buffers import RecordingCapacityError
from gfootball.recording_directory import directory_reservations


@dataclass(frozen=True)
class OutputLimits:
  dump_bytes: int = 128 * 1024 * 1024
  video_bytes: int = 512 * 1024 * 1024
  total_bytes: int = 4 * 1024 * 1024 * 1024
  total_files: int = 256
  active_dumps: int = 4
  steps: int = 10000
  video_frames: int = 100000
  scan_entries: int = 4096

  def __post_init__(self):
    for name, minimum, maximum in (
        ('dump_bytes', 128, 1024 * 1024 * 1024),
        ('video_bytes', 128, 2 * 1024 * 1024 * 1024),
        ('total_bytes', 128, 16 * 1024 * 1024 * 1024),
        ('total_files', 1, 4096), ('active_dumps', 1, 16),
        ('steps', 1, 100000), ('video_frames', 1, 1000000),
        ('scan_entries', 1, 16384)):
      value = getattr(self, name)
      if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid recording output limit: ' + name)


@dataclass(frozen=True)
class VideoSettings:
  width: int
  height: int
  fps: float
  format: str = 'avi'
  quality: int = 0

  def __post_init__(self):
    if any(type(v) is not int or not 2 <= v <= 4096 for v in (self.width, self.height)):
      raise ValueError('Video dimensions must be integers within 2..4096')
    if (type(self.fps) not in (int, float) or not math.isfinite(self.fps)
        or not 1 <= self.fps <= 240):
      raise ValueError('Video FPS must be finite and within 1..240')
    if self.format not in ('avi', 'webm') or type(self.quality) is not int or self.quality not in (0, 1, 2):
      raise ValueError('Invalid video format or quality')

  @property
  def dimensions(self):
    scale = min(1, 800 / self.width, 450 / self.height) if self.quality == 0 else 1
    # Even dimensions prevent codecs from silently cropping the last row/column.
    return tuple(max(2, int(size * scale) // 2 * 2) for size in (self.width, self.height))

  @property
  def fourcc(self):
    code = ('XVID', 'MJPG', 'png ')[self.quality] if self.format == 'avi' else 'vp80'
    return cv2.VideoWriter_fourcc(*code)


# 2026-09-09: coordinate separate owners and processes through live OS leases;
# the original per-instance counters could admit simultaneous excess output.
# class OutputBudget:
#   """Reserve complete output allowances before admitting another active dump.
#
# Share one instance for concurrent producers in a process. A new instance scans
# existing files so sequential environment resets do not reset the disk allowance.
# Subdirectory contents are outside the flat recording directory's accounting.
# """
#   def __init__(self, directory, limits=None):
#     self.directory = Path(directory).resolve()
#     self.limits = limits or OutputLimits()
#     if not isinstance(self.limits, OutputLimits):
#       raise ValueError('Expected OutputLimits')
#     self._lock = threading.RLock()
#     self._reservations = {}
#
#   def reserve(self, video=False):
#     if type(video) is not bool:
#       raise ValueError('Video reservation flag must be a bool')
#     with self._lock:
#       if len(self._reservations) >= self.limits.active_dumps:
#         raise RecordingCapacityError('Active dump count exceeded')
#       self.directory.mkdir(parents=True, exist_ok=True)
#       owned = {path for reservation in self._reservations.values() for path in reservation[2]}
#       size = sum(item[0] for item in self._reservations.values())
#       files = sum(item[1] for item in self._reservations.values())
#       with os.scandir(self.directory) as entries:
#         for count, entry in enumerate(entries, 1):
#           if count > self.limits.scan_entries:
#             raise RecordingCapacityError('Recording directory scan limit exceeded')
#           if Path(entry.path) in owned:
#             continue
#           info = entry.stat(follow_symlinks=False)
#           if stat.S_ISREG(info.st_mode):
#             size += info.st_size
#             files += 1
#           elif not stat.S_ISDIR(info.st_mode):
#             raise ValueError('Recording directory contains a non-regular entry')
#       requested = self.limits.dump_bytes + (self.limits.video_bytes if video else 0)
#       count = 2 if video else 1
#       if size + requested > self.limits.total_bytes or files + count > self.limits.total_files:
#         raise RecordingCapacityError('Recording directory output budget exceeded')
#       token = object()
#       self._reservations[token] = (requested, count, set())
#       return token
#
#   def temporary(self, token, suffix):
#     with self._lock:
#       paths = self._reservations[token][2]
#       if len(paths) >= self._reservations[token][1]:
#         raise RecordingCapacityError('Too many files for recording reservation')
#       fd, name = tempfile.mkstemp(prefix='.recording-', suffix=suffix, dir=self.directory)
#       path = Path(name)
#       paths.add(path)
#       return fd, path
#
#   def release(self, token):
#     with self._lock:
#       self._reservations.pop(token, None)
#
#   def stats(self):
#     with self._lock:
#       return dict(active_dumps=len(self._reservations),
#                   reserved_bytes=sum(item[0] for item in self._reservations.values()),
#                   reserved_files=sum(item[1] for item in self._reservations.values()))
class OutputBudget:
  """Per-owner accounting backed by shared process and OS directory leases."""
  def __init__(self, directory, limits=None):
    self.limits = limits or OutputLimits()
    if not isinstance(self.limits, OutputLimits):
      raise ValueError('Expected OutputLimits')
    self._directory = directory_reservations(directory)
    self.directory = self._directory.directory
    self._lock = threading.RLock()
    self._reservations = {}
    self._pid = os.getpid()

  def _check_process(self):
    if self._pid != os.getpid():
      raise RuntimeError('Recording budget cannot be used after fork')

  def reserve(self, video=False):
    self._check_process()
    if type(video) is not bool:
      raise ValueError('Video reservation flag must be a bool')
    with self._lock:
      token = self._directory.reserve(self.limits, video)
      self._reservations[token] = (self.limits.dump_bytes + (self.limits.video_bytes if video else 0),
                                   2 if video else 1)
      return token

  def temporary(self, token, suffix):
    self._check_process()
    with self._lock:
      if token not in self._reservations:
        raise ValueError('Recording reservation does not belong to this owner')
      return self._directory.temporary(token, suffix)

  @contextmanager
  # 2026-09-09: retry cleanup of orphan files under the directory guard as well.
  # def transaction(self, token):
  def transaction(self, token, cleanup=False):
    self._check_process()
    # Disabled output, failed construction and repeated cleanup own no lease.
    if token is None:
      # 2026-09-09: a prior deletion failure can leave owned files after release.
      # yield
      if cleanup:
        with self._directory.transaction():
          yield
      else:
        yield
      return
    with self._lock:
      if token not in self._reservations:
        raise ValueError('Recording reservation does not belong to this owner')
      token.check()
      with self._directory.transaction():
        yield

  def release(self, token):
    self._check_process()
    with self._lock:
      if token in self._reservations:
        self._directory.release(token)
        del self._reservations[token]

  def stats(self):
    self._check_process()
    with self._lock:
      return dict(active_dumps=len(self._reservations),
                  reserved_bytes=sum(item[0] for item in self._reservations.values()),
                  reserved_files=sum(item[1] for item in self._reservations.values()))


class _BoundedFile:
  def __init__(self, stream, maximum):
    self.stream, self.maximum, self.size = stream, maximum, 0

  def write(self, data):
    view = memoryview(data).cast('B')
    if view.nbytes > self.maximum - self.size:
      raise RecordingCapacityError('Dump file byte budget exceeded')
    length = view.nbytes
    while view:
      written = self.stream.write(view)
      if written is None or written <= 0 or written > len(view):
        raise OSError('Recording write made no valid progress')
      self.size += written
      view = view[written:]
    return length


def _identity(path):
  info = path.lstat()
  if not stat.S_ISREG(info.st_mode):
    raise OSError('Recording path is no longer a regular file')
  return info.st_dev, info.st_ino


def _unlink_owned(path, identity):
  try:
    current = _identity(path)
  except FileNotFoundError:
    return
  if current != identity:
    raise OSError('Recording path changed ownership during cleanup')
  path.unlink()


class RecordingOutput:
  """Own one dump and optional video; finalize explicitly, abort on any failure."""
  def __init__(self, stem, budget, video=None, enabled=True):
    # Generated stems add a timestamp to a separately validated public dump name.
    if type(stem) is not str or not stem or len(stem) > 128:
      raise ValueError('Invalid recording file stem')
    # 2026-09-09: a generated Unicode stem needs its own 128-byte allowance;
    # validating a 64-character slice wrongly reapplied the public 64-byte cap.
    # validate_dump_name(stem[:64].rstrip('. '))
    # if any(ord(c) < 32 or c in '/\\:*?"<>|' for c in stem) or stem[-1] in '. ':
    if (len(stem.encode('utf-8')) > 128 or stem[-1] in '. '
        or any(ord(c) < 32 or c in '/\\:*?"<>|' for c in stem)
        or re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', stem.split('.')[0], re.IGNORECASE)):
      raise ValueError('Invalid recording file stem')
    if not isinstance(budget, OutputBudget) or (video is not None and not isinstance(video, VideoSettings)):
      raise ValueError('Invalid recording output configuration')
    if type(enabled) is not bool:
      raise ValueError('Recording enabled must be a bool')
    self.budget, self.video, self.enabled = budget, video, enabled
    self.name = str(budget.directory / stem)
    self._lock = threading.RLock()
    self._pid = os.getpid()
    self._token = None
    self._owned = {}
    self._dump = None
    self._video_writer = None
    self._dump_path = self._video_path = None
    self._steps = self._frames = 0
    self._closed = False
    self._result = {}
    if not enabled:
      return
    try:
      self._token = budget.reserve(video is not None)
      fd, self._dump_path = budget.temporary(self._token, '.dump.part')
      # 2026-09-09: even a metadata failure must close the freshly created fd.
      # self._owned[self._dump_path] = _identity(self._dump_path)
      try:
        self._owned[self._dump_path] = _identity(self._dump_path)
        stream = os.fdopen(fd, 'wb', buffering=0)
      except BaseException:
        os.close(fd)
        raise
      self._dump = _BoundedFile(stream, budget.limits.dump_bytes)
      if video is not None:
        fd, self._video_path = budget.temporary(self._token, '.' + video.format)
        os.close(fd)  # OpenCV must open the path itself, including on Windows.
        self._owned[self._video_path] = _identity(self._video_path)
        self._video_writer = cv2.VideoWriter(str(self._video_path), video.fourcc,
                                             video.fps, video.dimensions)
        if not self._video_writer.isOpened():
          raise OSError('Video encoder could not open the recording')
        self._check_video_size()
    except BaseException as error:
      # 2026-09-09: cleanup must not replace the actual write/open failure.
      # self.abort()
      self._abort_after_error(error)
      raise

  def _abort_after_error(self, original):
    try:
      self.abort()
    except BaseException:
      # Keep the original exception and fixed diagnostic, not a retained traceback.
      if hasattr(original, 'add_note'):
        original.add_note('Recording cleanup also failed; inspect its private temporary files.')

  def _require_open(self):
    self._check_process()
    if self._closed:
      raise RuntimeError('Recording output is closed')

  def _check_process(self):
    if self._pid != os.getpid():
      raise RuntimeError('Recording output cannot be used after fork')

  def _check_video_size(self):
    if self._video_path is not None and self._video_path.stat().st_size > self.budget.limits.video_bytes:
      raise RecordingCapacityError('Video file byte budget exceeded')

  def write_step(self, record):
    with self._lock:
      self._require_open()
      try:
        if self._steps >= self.budget.limits.steps:
          raise RecordingCapacityError('Dump step count exceeded')
        if self._dump is not None:
          pickle.dump(record, self._dump, protocol=4)
        self._steps += 1
      except BaseException as error:
        # 2026-09-09: preserve the triggering error if cleanup also fails.
        # self.abort()
        self._abort_after_error(error)
        raise

  def write_frame(self, frame):
    """Write the final BGR overlay image, synchronously, without retaining it."""
    with self._lock:
      self._require_open()
      try:
        if self.video is None or not self.enabled:
          return
        if self._frames >= self.budget.limits.video_frames:
          raise RecordingCapacityError('Video frame count exceeded')
        width, height = self.video.dimensions
        if type(frame) is not np.ndarray or frame.dtype != np.uint8 or frame.shape != (height, width, 3):
          raise ValueError('Encoded frame must match the BGR video dimensions')
        self._video_writer.write(frame)
        self._frames += 1
        self._check_video_size()
      except BaseException as error:
        # 2026-09-09: preserve the triggering error if cleanup also fails.
        # self.abort()
        self._abort_after_error(error)
        raise

  def _close_resources(self):
    first = None
    writer, self._video_writer = self._video_writer, None
    if writer is not None:
      try:
        writer.release()
      except BaseException as error:
        first = error
    dump, self._dump = self._dump, None
    if dump is not None:
      try:
        dump.stream.close()
      except BaseException as error:
        first = first or error
    if first is not None:
      raise first

  # 2026-09-09: serialize file publication/cleanup with quota scans.
  # def abort(self):
  #   with self._lock:
  #     first = None
  #     try:
  #       self._close_resources()
  #     except BaseException as error:
  #       first = error
  #     for path, identity in tuple(self._owned.items()):
  #       try:
  #         _unlink_owned(path, identity)
  #         del self._owned[path]
  #       except BaseException as error:
  #         first = first or error
  #     self.budget.release(self._token)
  #     self._token = None
  #     self._closed = True
  #     if first is not None:
  #       raise first
  # 2026-09-09: always close resources/release leases even when the directory
  # guard fails; acquire output lock before directory lock consistently.
  # def abort(self):
  #   self._check_process()
  #   with self.budget.transaction(self._token):
  #     with self._lock:
  #       first = None
  #       try:
  #         self._close_resources()
  #       except BaseException as error:
  #         first = error
  #       for path, identity in tuple(self._owned.items()):
  #         try:
  #           _unlink_owned(path, identity)
  #           del self._owned[path]
  #         except BaseException as error:
  #           first = first or error
  #       self.budget.release(self._token)
  #       self._token = None
  #       self._closed = True
  #       if first is not None:
  #         raise first
  def abort(self):
    self._check_process()
    with self._lock:
      first = None
      try:
        self._close_resources()
      except BaseException as error:
        first = error
      try:
        with self.budget.transaction(self._token, cleanup=bool(self._owned)):
          for path, identity in tuple(self._owned.items()):
            try:
              _unlink_owned(path, identity)
              del self._owned[path]
            except BaseException as error:
              first = first or error
      except BaseException as error:
        first = first or error
      finally:
        self.budget.release(self._token)
        self._token = None
        self._closed = True
      if first is not None:
        raise first

  # 2026-09-09: serialize file publication/cleanup with quota scans.
  # def finalize(self):
  #   with self._lock:
  #     if self._closed:
  #       return dict(self._result)
  #     try:
  #       self._close_resources()
  #       self._check_video_size()
  #       selected = []
  #       if self._dump_path is not None and self._steps:
  #         selected.append(('dump', self._dump_path, Path(self.name + '.dump')))
  #       if self._video_path is not None and self._frames:
  #         selected.append(('video', self._video_path, Path(self.name + '.' + self.video.format)))
  #       for kind, source, destination in selected:
  #         os.link(source, destination)  # Exclusive publication; no overwrite fallback.
  #         self._owned[destination] = self._owned[source]
  #       # Keep all source files until the complete link phase succeeds, so a
  #       # collision on either destination can roll back only our new links.
  #       for kind, source, destination in selected:
  #         self._result[kind] = str(destination)
  #       for path, identity in tuple(self._owned.items()):
  #         if str(path) not in self._result.values():
  #           _unlink_owned(path, identity)
  #       self._owned.clear()  # Committed files now belong to the user.
  #       self.budget.release(self._token)
  #       self._token = None
  #       self._closed = True
  #       return dict(self._result)
  #     except BaseException as error:
  #       self._result.clear()
  #       # 2026-09-09: retain the publication/encoder error as the main failure.
  #       # self.abort()
  #       self._abort_after_error(error)
  #       raise
  # 2026-09-09: consistent lock order and cleanup when guard acquisition fails.
  # def finalize(self):
  #   self._check_process()
  #   with self.budget.transaction(self._token):
  #     with self._lock:
  #       if self._closed:
  #         return dict(self._result)
  #       try:
  #         self._close_resources()
  #         self._check_video_size()
  #         selected = []
  #         if self._dump_path is not None and self._steps:
  #           selected.append(('dump', self._dump_path, Path(self.name + '.dump')))
  #         if self._video_path is not None and self._frames:
  #           selected.append(('video', self._video_path, Path(self.name + '.' + self.video.format)))
  #         for kind, source, destination in selected:
  #           os.link(source, destination)  # Exclusive publication; no overwrite fallback.
  #           self._owned[destination] = self._owned[source]
  #         # Keep all source files until the complete link phase succeeds, so a
  #         # collision on either destination can roll back only our new links.
  #         for kind, source, destination in selected:
  #           self._result[kind] = str(destination)
  #         for path, identity in tuple(self._owned.items()):
  #           if str(path) not in self._result.values():
  #             _unlink_owned(path, identity)
  #         self._owned.clear()  # Committed files now belong to the user.
  #         self.budget.release(self._token)
  #         self._token = None
  #         self._closed = True
  #         return dict(self._result)
  #       except BaseException as error:
  #         self._result.clear()
  #         # 2026-09-09: retain the publication/encoder error as the main failure.
  #         # self.abort()
  #         self._abort_after_error(error)
  #         raise
  def finalize(self):
    self._check_process()
    with self._lock:
      if self._closed:
        return dict(self._result)
      try:
        with self.budget.transaction(self._token):
          self._close_resources()
          self._check_video_size()
          selected = []
          if self._dump_path is not None and self._steps:
            selected.append(('dump', self._dump_path, Path(self.name + '.dump')))
          if self._video_path is not None and self._frames:
            selected.append(('video', self._video_path, Path(self.name + '.' + self.video.format)))
          for kind, source, destination in selected:
            os.link(source, destination)
            self._owned[destination] = self._owned[source]
          for kind, source, destination in selected:
            self._result[kind] = str(destination)
          for path, identity in tuple(self._owned.items()):
            if str(path) not in self._result.values():
              _unlink_owned(path, identity)
          self._owned.clear()
          self.budget.release(self._token)
          self._token = None
          self._closed = True
          return dict(self._result)
      except BaseException as error:
        self._result.clear()
        self._abort_after_error(error)
        raise

  def stats(self):
    with self._lock:
      return dict(steps=self._steps, video_frames=self._frames, closed=self._closed)

  def __enter__(self):
    self._require_open()
    return self

  def __exit__(self, kind, value, tb):
    if kind is None:
      self.finalize()
    else:
      # 2026-09-09: cleanup must preserve the exception from the with body.
      # self.abort()
      self._abort_after_error(value)

  def __del__(self):
    # Destruction cannot certify a complete episode; never publish implicitly.
    if hasattr(self, '_lock'):
      try:
        self.abort()
      except BaseException:
        pass
