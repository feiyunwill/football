"""Working-tree export must include dirty/new inputs and reject later changes."""
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

TOOL = Path(__file__).with_name('snapshot_current.py')


class SnapshotCurrentTest(unittest.TestCase):
    def test_dirty_and_new_inputs_without_git_mutation_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'repo'; root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'engine').mkdir()
            tracked = root / 'engine/tracked.cpp'; tracked.write_bytes(b'old\n')
            subprocess.run(['git', 'add', 'engine/tracked.cpp'], cwd=root, check=True)
            index = (root / '.git/index').read_bytes()
            tracked.write_bytes(b'current\r\n')
            (root / 'engine/new.hpp').write_bytes(b'new\n')
            (root/'engine/data').mkdir()
            (root/'.gitignore').write_text('engine/data/cache.dat\n')
            (root/'engine/data/cache.dat').write_bytes(b'actual runtime input\n')
            archive, receipt, exported = [base / name for name in ('source.tar', 'inputs.json', 'exported')]
            subprocess.run([sys.executable, TOOL, 'create', root, archive, receipt], check=True, capture_output=True)
            with tarfile.open(archive) as stream:
                stream.extractall(exported, filter='data')
            self.assertEqual((exported / 'engine/tracked.cpp').read_bytes(), b'current\r\n')
            self.assertEqual((exported / 'engine/new.hpp').read_bytes(), b'new\n')
            self.assertEqual((root / '.git/index').read_bytes(), index)
            self.assertEqual(len(json.loads(receipt.read_text())['inputs']), 3)
            self.assertEqual((exported/'engine/data/cache.dat').read_bytes(),b'actual runtime input\n')
            subprocess.run([sys.executable, TOOL, 'verify', root, exported, receipt], check=True, capture_output=True)
            (exported / 'engine/new.hpp').write_bytes(b'tampered\n')
            result = subprocess.run([sys.executable, TOOL, 'verify', root, exported, receipt], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            (exported / 'engine/new.hpp').write_bytes(b'new\n')
            (root / 'engine/late.hpp').write_bytes(b'late\n')
            result = subprocess.run([sys.executable, TOOL, 'verify', root, exported, receipt], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / '.git/index').read_bytes(), index)


if __name__ == '__main__':
    unittest.main()
