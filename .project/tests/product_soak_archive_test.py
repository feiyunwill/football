"""A saved soak bundle must reject changed raw measurements."""
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from archive_product_soak import verify_archive


class SoakArchiveTest(unittest.TestCase):
    def test_bundle_detects_member_and_report_reference_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = b'measured frame samples\n'
            log_sha = hashlib.sha256(log).hexdigest()
            report = {'passed': True, 'skipped': 0, 'assertions': 300,
                      'seeds': [42, 43, 44], 'frames_per_seed': 36000,
                      'measured_frames_by_build': {'release': 108000,
                                                   'sanitized': 108000},
                      'source_manifest_sha256': 'a' * 64, 'binaries': {},
                      'commands': [{'label': 'release-42',
                                    'log_sha256': log_sha}],
                      'runs': [{'build': build, 'seed': seed,
                                'log_sha256': log_sha}
                               for build in ('release', 'sanitized')
                               for seed in (42, 43, 44)]}

            def bundle(name, raw_log, reported_hash):
                report['commands'][0]['log_sha256'] = reported_hash
                report['runs'][0]['log_sha256'] = reported_hash
                content = {'report.json': json.dumps(report).encode()}
                content.update({f"{run['build']}-{run['seed']}.log":
                                raw_log if run['build'] == 'release' and run['seed'] == 42
                                else log for run in report['runs']})
                manifest = {'schema': 'football-product-soak-archive-v1',
                            'source_commit': 'f' * 40,
                            'source_manifest_sha256': 'a' * 64,
                            'binary_hashes': {},
                            'files': {key: hashlib.sha256(value).hexdigest()
                                      for key, value in content.items()}}
                path = root / name
                with zipfile.ZipFile(path, 'w') as archive:
                    for key, value in content.items():
                        archive.writestr(key, value)
                    archive.writestr('manifest.json', json.dumps(manifest))
                return path

            intact = bundle('intact.zip', log, log_sha)
            self.assertEqual(verify_archive(intact)['logs'], 6)
            changed = bundle('changed.zip', log + b'changed', log_sha)
            with self.assertRaisesRegex(RuntimeError, 'measured|command'):
                verify_archive(changed)


if __name__ == '__main__':
    unittest.main()
