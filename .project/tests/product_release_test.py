"""Release evidence must retain the exact logs and wheel it accepted."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'checks'))
from product_release import audit_artifact_children


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReleaseArtifactTest(unittest.TestCase):
    def test_accepts_intact_artifact_and_rejects_changed_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            probe = root / 'installed-probe/report.json'
            probe.parent.mkdir()
            files = {
                root / 'build.log': b'compiler output\n',
                root / 'release-42.log': b'measured run\n',
                root / 'wheel/package.whl': b'wheel bytes',
                probe: b'{"passed": true}\n',
            }
            for path, data in files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            report = root / 'report.json'
            report.write_text(json.dumps({
                'commands': [{'label': 'build',
                              'log_sha256': digest(files[root / 'build.log'])}],
                'runs': [{'build': 'release', 'seed': 42,
                          'log_sha256': digest(files[root / 'release-42.log'])}],
                'wheel': {'path': str(root / 'wheel/package.whl'),
                          'sha256': digest(files[root / 'wheel/package.whl'])},
                'build': {'wheel_sha256': digest(files[root / 'wheel/package.whl'])},
                'probe_report_sha256': digest(files[probe]),
            }))

            def failures():
                found = []
                audited = audit_artifact_children(
                    report, lambda okay, message: found.append(message) if not okay else None)
                return found, audited

            problems, audited = failures()
            self.assertEqual(problems, [])
            self.assertEqual(len(audited), 4)
            for path, original in files.items():
                with self.subTest(path=path.name):
                    path.write_bytes(original + b'changed')
                    self.assertTrue(failures()[0])
                    path.write_bytes(original)

    def test_rejects_log_outside_artifact_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outer = root / 'outside.log'
            outer.write_bytes(b'valid bytes')
            folder = root / 'artifact'
            folder.mkdir()
            report = folder / 'report.json'
            report.write_text(json.dumps({'commands': [{
                'log': '../outside.log', 'log_sha256': digest(outer.read_bytes())}]}))
            failures = []
            audit_artifact_children(
                report, lambda okay, message: failures.append(message) if not okay else None)
            self.assertTrue(failures)


if __name__ == '__main__':
    unittest.main()
