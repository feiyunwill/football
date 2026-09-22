"""Reject mismatched saved inputs/hashes even when shutdown lengths differ."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'checks'))
from replay_persistence import compare_confirmed_prefix, read_replay, verify_actual_wire


class ReplayEvidenceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fixture(self, name, count, *, changed_input=None, changed_hash=None, seed=42):
        scenario = b'probe'
        records = []
        authority, hashes = bytearray(), bytearray()
        for frame in range(count):
            inputs = struct.pack('<ffH', (frame % 3) / 2, 0, frame % 2) * 2
            saved_inputs = struct.pack('<ffH', -1, 0, 0) * 2 if frame == changed_input else inputs
            state_hash = 100 + frame
            records.append(struct.pack('<IQ', frame, state_hash + (frame == changed_hash)) + saved_inputs)
            authority.extend(struct.pack('<BIH', 3, frame, 2) + inputs)
            if frame % 10 == 0:
                hashes.extend(struct.pack('<BIQ', 4, frame, state_hash))
        final_hash = 99 + count + (count - 1 == changed_hash)
        data = (struct.pack('<II', seed, len(scenario)) + scenario +
                struct.pack('<IIQI', count, 2, final_hash, count) + b''.join(records))
        path = self.root / name
        path.write_bytes(data)
        return path, read_replay(path), bytes(authority), bytes(hashes)

    def pair(self, first, second):
        return compare_confirmed_prefix([first[0], second[0]], [first[1], second[1]])

    def test_equal_saved_files_compare_every_frame(self):
        first, second = self.fixture('a', 21), self.fixture('b', 21)
        self.assertEqual(first[1], second[1])
        self.assertEqual(self.pair(first, second)['shared_frames'], 21)

    def test_abrupt_shutdown_retains_both_original_lengths(self):
        first, second = self.fixture('a', 20), self.fixture('b', 21)
        before = [row[0].read_bytes() for row in (first, second)]
        result = self.pair(first, second)
        self.assertEqual(result['shared_frames'], 20)
        self.assertEqual(result['terminal_frames'], [20, 21])
        self.assertEqual(before, [row[0].read_bytes() for row in (first, second)])

    def test_changed_shared_input_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'record 7'):
            self.pair(self.fixture('a', 20), self.fixture('b', 21, changed_input=7))

    def test_changed_shared_intermediate_hash_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'record 7'):
            self.pair(self.fixture('a', 20), self.fixture('b', 21, changed_hash=7))

    def test_different_session_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'session differs'):
            self.pair(self.fixture('a', 20), self.fixture('b', 21, seed=43))

    def test_truncated_file_is_rejected_before_comparison(self):
        path = self.fixture('a', 21)[0]
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(RuntimeError, 'missing replay bytes'):
            read_replay(path)

    def capture(self, row):
        for index in (1, 2):
            (self.root / f'authority{index}.bin').write_bytes(row[2])
            (self.root / f'hashes{index}.bin').write_bytes(row[3])

    def test_fixed_wire_rejects_saved_input_change(self):
        valid = self.fixture('a', 21)
        self.capture(valid)
        self.assertEqual(verify_actual_wire(valid[0], valid[1], self.root)['frames'], 21)
        changed = self.fixture('b', 21, changed_input=19)
        with self.assertRaisesRegex(RuntimeError, 'Saved input differs'):
            verify_actual_wire(changed[0], changed[1], self.root)

    def test_fixed_wire_rejects_saved_checkpoint_change(self):
        valid = self.fixture('a', 21)
        self.capture(valid)
        changed = self.fixture('b', 21, changed_hash=10)
        with self.assertRaisesRegex(RuntimeError, 'Saved checkpoint differs'):
            verify_actual_wire(changed[0], changed[1], self.root)


if __name__ == '__main__':
    unittest.main()
