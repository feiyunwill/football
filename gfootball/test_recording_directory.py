# 2026-09-09: actual independent owners/processes, OS leases and crash recovery.
import json
import gc
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from gfootball.recording_buffers import RecordingCapacityError
from gfootball.recording_directory import CONTROL_NAME, METADATA_BYTES, SLOTS, _lock_descriptors
from gfootball.recording_output import OutputBudget, OutputLimits, RecordingOutput


def directory_worker(directory, limits, stem, connection, start=None):
  output = None
  try:
    connection.send(('booted', os.getpid()))
    if start is not None and not start.wait(15):
      raise TimeoutError('Test start signal missing')
    budget = OutputBudget(directory, OutputLimits(**limits))
    try:
      output = RecordingOutput(stem, budget)
      output.write_step({'worker': stem})
    except (ValueError, OSError) as error:
      connection.send(('rejected', type(error).__name__, str(error)))
      return
    connection.send(('opened', str(output._dump_path), budget.stats()))
    while connection.poll(15):
      command = connection.recv()
      if command == 'abort':
        output.abort()
        connection.send(('aborted', budget.stats()))
        return
      if command == 'finalize':
        connection.send(('finalized', output.finalize()))
        return
      if command == 'crash':
        os._exit(29)
      if command == 'guard':
        with budget._directory.transaction():
          connection.send(('locked',))
          if not connection.poll(15) or connection.recv() != 'release_guard':
            raise TimeoutError('Test guard release missing')
        connection.send(('unlocked',))
  finally:
    if output is not None:
      output.abort()
    connection.close()


class RecordingDirectoryTest(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory(prefix='football-directory-test-')
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)
    self.context = multiprocessing.get_context('spawn')
    self.fd_baseline = set(_lock_descriptors)
    self.addCleanup(self.check_descriptors)

  def check_descriptors(self):
    self.assertEqual(_lock_descriptors, self.fd_baseline)

  def budget(self, **options):
    return OutputBudget(self.directory, OutputLimits(**options))

  def create(self, stem, budget):
    output = RecordingOutput(stem, budget)
    self.addCleanup(output.abort)
    return output

  def receive(self, connection):
    self.assertTrue(connection.poll(10), 'Owned recording worker did not reply')
    return connection.recv()

  def spawn(self, stem, start=None, **limits):
    parent, child = self.context.Pipe()
    process = self.context.Process(target=directory_worker,
        args=(str(self.directory), limits, stem, child, start),
        name='football-recording-directory-test-' + stem)
    process.start()
    child.close()
    self.addCleanup(self.stop, process, parent)
    self.assertEqual(self.receive(parent)[0], 'booted')
    return process, parent

  def stop(self, process, connection):
    if process.is_alive():
      try:
        connection.send('abort')
      except (EOFError, OSError):
        pass
      process.join(3)
    if process.is_alive():
      process.terminate()  # Only this test's explicitly owned worker.
      process.join(3)
    self.assertFalse(process.is_alive())
    connection.close()
    process.close()

  def payloads(self):
    return sorted(path for path in self.directory.iterdir() if path.name != CONTROL_NAME)

  def test_independent_owners_and_path_aliases_share_admission(self):
    options = dict(active_dumps=1)
    first = self.create('one', self.budget(**options))
    alias = OutputBudget(self.directory / 'unused' / '..', OutputLimits(**options))
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('two', alias)
    first.abort()
    second = self.create('two', alias)
    second.abort()
    self.assertEqual(self.payloads(), [])

  def test_conflicting_active_directory_policies_reject_but_idle_can_reconfigure(self):
    first = self.create('one', self.budget(active_dumps=1))
    with self.assertRaisesRegex(ValueError, 'policies must match'):
      RecordingOutput('two', self.budget(active_dumps=2))
    first.abort()
    self.create('two', self.budget(active_dumps=2))

  def test_all_sixteen_slots_are_bounded_reusable_and_identity_checked(self):
    options = dict(active_dumps=16, dump_bytes=128, total_bytes=2048, total_files=16)
    outputs = [self.create('slot%d' % slot, self.budget(**options)) for slot in range(SLOTS)]
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('extra', self.budget(**options))
    metadata = list((self.directory / CONTROL_NAME).iterdir())
    self.assertEqual(len(metadata), 2 * SLOTS + 1)
    self.assertTrue(all(path.stat().st_size <= METADATA_BYTES for path in metadata))
    outputs[7].abort()
    replacement = self.create('replacement', self.budget(**options))
    self.assertEqual(replacement._token.slot, 7)
    for output in outputs + [replacement]:
      output.abort()
    self.assertEqual(self.payloads(), [])

  def test_foreign_owner_cannot_create_files_or_release_another_lease(self):
    a, b = self.budget(active_dumps=1), self.budget(active_dumps=1)
    first = self.create('first', a)
    b.release(first._token)
    with self.assertRaises(ValueError):
      b.temporary(first._token, '.dump.part')
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('second', b)
    with self.assertRaises(ValueError):
      a.temporary(first._token, '../../escape')

  def test_direct_lease_ownership_reclaims_slot_after_last_reference_is_gone(self):
    budget = self.budget(active_dumps=1)
    lease = budget.reserve()
    del budget
    gc.collect()
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('still_owned', self.budget(active_dumps=1))
    del lease
    gc.collect()
    self.create('reclaimed', self.budget(active_dumps=1))

  def test_failed_lease_creation_cannot_later_close_a_reused_unrelated_descriptor(self):
    budget = self.budget()
    retained = []
    with mock.patch.object(budget._directory, '_store', side_effect=OSError('metadata write failed')):
      try:
        budget.reserve()
      except OSError as error:
        retained.append(error)  # Keep the failed constructor's traceback alive.
    self.assertEqual(len(retained), 1)
    borrowed = []
    try:
      for index in range(3):
        borrowed.append(os.open(self.directory / ('other%d' % index), os.O_RDWR | os.O_CREAT, 0o600))
      retained.clear()
      gc.collect()
      for fd in borrowed:
        os.write(fd, b'still owned by caller')
        self.assertGreater(os.fstat(fd).st_size, 0)
    finally:
      for fd in borrowed:
        os.close(fd)
    self.assertEqual(budget.stats()['active_dumps'], 0)

  def test_publication_holds_directory_guard_until_lease_becomes_committed_files(self):
    options = dict(dump_bytes=128, total_bytes=256, total_files=1)
    output = self.create('publish', self.budget(**options))
    output.write_step({'frame': 0})
    linked, proceed, trying, finished = (threading.Event() for _ in range(4))
    errors, results = [], []
    original_link = os.link

    def pause_link(source, destination):
      original_link(source, destination)
      linked.set()
      if not proceed.wait(5):
        raise TimeoutError('Test publication release missing')

    def finalizer():
      try:
        results.append(output.finalize())
      except BaseException as error:
        errors.append(type(error).__name__)

    def admission():
      trying.set()
      try:
        RecordingOutput('racer', self.budget(**options))
      except BaseException as error:
        errors.append(type(error).__name__)
      finally:
        finished.set()

    with mock.patch('gfootball.recording_output.os.link', side_effect=pause_link):
      a = threading.Thread(target=finalizer, name='football-recording-directory-publish')
      b = threading.Thread(target=admission, name='football-recording-directory-admit')
      a.start()
      self.assertTrue(linked.wait(5))
      b.start()
      self.assertTrue(trying.wait(5))
      self.assertFalse(finished.wait(0.05))
      proceed.set()
      a.join(5)
      b.join(5)
      self.assertFalse(a.is_alive() or b.is_alive())
    self.assertEqual(errors, ['RecordingCapacityError'])
    self.assertEqual(len(results), 1)
    self.assertEqual(self.payloads(), [Path(results[0]['dump'])])

  def test_actual_processes_compete_for_one_directory_byte_budget(self):
    limits = dict(dump_bytes=512, total_bytes=1024, total_files=4, active_dumps=4)
    first, first_pipe = self.spawn('first', **limits)
    second, second_pipe = self.spawn('second', **limits)
    self.assertEqual(self.receive(first_pipe)[0], 'opened')
    self.assertEqual(self.receive(second_pipe)[0], 'opened')
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('third', self.budget(**limits))
    first_pipe.send('abort')
    self.assertEqual(self.receive(first_pipe)[0], 'aborted')
    first.join(5)
    self.assertEqual(first.exitcode, 0)
    replacement = self.create('third', self.budget(**limits))
    replacement.abort()
    second_pipe.send('finalize')
    result = self.receive(second_pipe)
    self.assertEqual(result[0], 'finalized')
    second.join(5)
    self.assertEqual(second.exitcode, 0)
    self.assertTrue(Path(result[1]['dump']).exists())

  def test_simultaneous_spawn_admissions_never_exceed_file_or_active_caps(self):
    limits = dict(dump_bytes=128, total_bytes=2048, total_files=2, active_dumps=2)
    start = self.context.Event()
    workers = [self.spawn('race%d' % index, start, **limits) for index in range(4)]
    start.set()
    results = [self.receive(pipe) for _, pipe in workers]
    self.assertEqual(sum(value[0] == 'opened' for value in results), 2)
    self.assertEqual(sum(value[:2] == ('rejected', 'RecordingCapacityError') for value in results), 2)
    self.assertEqual(len(self.payloads()), 2)

  def test_crashed_process_releases_os_slot_and_orphans_still_count(self):
    limits = dict(dump_bytes=128, total_bytes=256, total_files=2, active_dumps=1)
    process, connection = self.spawn('crash', **limits)
    opened = self.receive(connection)
    self.assertEqual(opened[0], 'opened')
    orphan = Path(opened[1])
    before = orphan.read_bytes()
    connection.send('crash')
    process.join(5)
    self.assertEqual(process.exitcode, 29)
    replacement = self.create('replacement', self.budget(**limits))
    self.assertTrue(orphan.exists())
    self.assertEqual(orphan.read_bytes(), before)
    replacement.abort()
    # A fresh owner cannot ignore that orphan just because its process died.
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('full', self.budget(dump_bytes=128, total_files=1))
    self.assertEqual(self.payloads(), [orphan])

  def test_cross_process_policy_mismatch_is_explicit_and_preserves_owner(self):
    first = self.create('one', self.budget(active_dumps=1))
    process, connection = self.spawn('mismatch', active_dumps=2)
    result = self.receive(connection)
    self.assertEqual(result[:2], ('rejected', 'ValueError'))
    process.join(5)
    self.assertEqual(process.exitcode, 0)
    first.write_step({'still_usable': True})

  def test_real_os_guard_contention_times_out_and_recovers(self):
    process, connection = self.spawn('guard')
    self.assertEqual(self.receive(connection)[0], 'opened')
    connection.send('guard')
    self.assertEqual(self.receive(connection)[0], 'locked')
    with self.assertRaises(TimeoutError):
      RecordingOutput('waiting', self.budget())
    connection.send('release_guard')
    self.assertEqual(self.receive(connection)[0], 'unlocked')
    self.create('after', self.budget())

  def test_corrupt_active_metadata_fails_closed_then_stale_slot_recovers(self):
    first = self.create('one', self.budget())
    record_path = self.directory / CONTROL_NAME / ('slot-%d.json' % first._token.slot)
    with first.budget._directory.transaction():
      record_path.write_text('{bad', encoding='ascii')
    with self.assertRaises(ValueError):
      RecordingOutput('two', self.budget())
    self.assertTrue(first._dump_path.exists())
    first.abort()
    second = self.create('two', self.budget())
    self.assertEqual(json.loads(record_path.read_text(encoding='ascii'))['token'], second._token.record['token'])

  def test_control_directory_unknown_or_oversized_content_is_preserved(self):
    control = self.directory / CONTROL_NAME
    control.mkdir()
    unknown = control / 'user-document'
    unknown.write_bytes(b'keep me')
    with self.assertRaises(ValueError):
      RecordingOutput('one', self.budget())
    self.assertEqual(unknown.read_bytes(), b'keep me')
    unknown.unlink()  # Test-owned exact file, no recursive operation.
    oversized = control / 'slot-0.json'
    oversized.write_bytes(b'x' * (METADATA_BYTES + 1))
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('one', self.budget())
    self.assertEqual(oversized.stat().st_size, METADATA_BYTES + 1)

  def test_control_marker_conflict_preserves_file(self):
    control = self.directory / CONTROL_NAME
    control.mkdir()
    guard = control / 'guard'
    guard.write_bytes(b'user data')
    with self.assertRaises(ValueError):
      RecordingOutput('one', self.budget())
    self.assertEqual(guard.read_bytes(), b'user data')

  def test_failure_to_acquire_cleanup_guard_still_closes_stream_and_releases_slot(self):
    budget = self.budget()
    output = self.create('one', budget)
    stream = output._dump.stream
    with mock.patch.object(budget._directory, 'transaction', side_effect=OSError('guard unavailable')):
      with self.assertRaisesRegex(OSError, 'guard unavailable'):
        output.abort()
    self.assertTrue(stream.closed)
    self.assertEqual(budget.stats()['active_dumps'], 0)
    self.assertTrue(output._dump_path.exists())
    output.abort()
    self.assertEqual(self.payloads(), [])

  def test_finalize_guard_failure_aborts_without_leaking_descriptor_or_publishing(self):
    budget = self.budget()
    output = self.create('one', budget)
    output.write_step({'frame': 0})
    stream = output._dump.stream
    with mock.patch.object(budget._directory, 'transaction', side_effect=OSError('guard unavailable')):
      with self.assertRaisesRegex(OSError, 'guard unavailable'):
        output.finalize()
    self.assertTrue(stream.closed)
    self.assertEqual(budget.stats()['active_dumps'], 0)
    self.assertFalse(Path(output.name + '.dump').exists())
    output.abort()

  def test_concurrent_write_error_and_finalize_use_consistent_lock_order(self):
    output = self.create('threads', self.budget())
    writing, release = threading.Event(), threading.Event()
    errors, results = [], []

    def fail_write(data):
      writing.set()
      if not release.wait(5):
        raise TimeoutError('Test write release missing')
      raise OSError('injected disk failure')

    def writer():
      try:
        output.write_step({'value': 1})
      except OSError as error:
        errors.append(str(error))

    def finalize():
      results.append(output.finalize())

    with mock.patch.object(output._dump, 'write', side_effect=fail_write):
      a = threading.Thread(target=writer, name='football-recording-directory-write')
      b = threading.Thread(target=finalize, name='football-recording-directory-finalize')
      a.start()
      self.assertTrue(writing.wait(5))
      b.start()
      release.set()
      a.join(5)
      b.join(5)
      self.assertFalse(a.is_alive() or b.is_alive())
    self.assertEqual(errors, ['injected disk failure'])
    self.assertEqual(results, [{}])
    self.assertEqual(self.payloads(), [])


if __name__ == '__main__':
  unittest.main()
