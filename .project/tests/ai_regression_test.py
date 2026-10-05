"""The AI cohort must detect changes to its runtime data, not only C++ sources."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'checks'))
import ai_regression


class AIInputManifestTest(unittest.TestCase):
    def test_runtime_data_change_invalidates_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / 'engine/data/databases/default/teams.db'
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b'baseline')
            with patch.object(ai_regression, 'ROOT', root):
                before = ai_regression.source_manifest()
                self.assertIn('engine/data/databases/default/teams.db', before)
                asset.write_bytes(b'changed')
                after = ai_regression.source_manifest()
                self.assertNotEqual(before, after)


if __name__ == '__main__':
    unittest.main()
