"""Failure injection for acceptance evidence; no engine dependencies needed."""
import copy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

import quality


class QualityTest(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.root = Path(self.directory.name)
    self.current = {'sha256': 'current', 'files': 1, 'manifest': {'source': 'hash'}}
    self.environment = {'interpreter': 'validated', 'tools': 'validated'}
    self.report = dict(passed=True, acceptance_schema=2,
                       runner_sha256=quality.validate.sha(Path(quality.validate.__file__)),
                       source_before=self.current, source_after=self.current, commands=[])
    self.report.update(environment_before=self.environment, environment_after=self.environment)
    self.report['acceptance_inputs'] = {name: quality.validate.sha(quality.validate.ROOT / name)
                                        for name in quality.validate.ACCEPTANCE_FILES}
    for name in sorted(quality.REQUIRED):
      log = self.root / (name + '.log')
      log.write_text('\nRan 72 tests in 1.0s\n\nOK\n' if name == 'python-integration' else 'success\n')
      self.report['commands'].append(dict(name=name, log=log.name, exit_code=0,
                                           sha256=quality.validate.sha(log)))
    self.fingerprint = patch.object(quality.validate, 'source_fingerprint', return_value=self.current)
    self.fingerprint.start()
    self.addCleanup(self.fingerprint.stop)
    self.runtime = patch.object(quality.validate, 'runtime_identity', return_value=self.environment)
    self.runtime.start()
    self.addCleanup(self.runtime.stop)

  def verify(self, report=None):
    path = self.root / 'report.json'
    path.write_text(json.dumps(self.report if report is None else report))
    return quality.verify(path)

  def test_complete_evidence_passes(self):
    self.assertTrue(self.verify()['passed'])

  def test_failure_missing_duplicate_and_stale_rejected(self):
    for field, value in [('passed', False), ('acceptance_schema', 0),
                         ('runner_sha256', 'old'), ('acceptance_inputs', {}),
                         ('environment_before', {}), ('environment_after', {}),
                         ('source_before', {}), ('source_after', {})]:
      with self.subTest(field=field):
        report = copy.deepcopy(self.report); report[field] = value
        with self.assertRaises(ValueError): self.verify(report)

  def test_changed_runtime_dependencies_or_tools_rejected(self):
    for environment in ({'interpreter': 'different', 'tools': 'validated'},
                        {'interpreter': 'validated', 'tools': 'different'}):
      with patch.object(quality.validate, 'runtime_identity', return_value=environment):
        with self.assertRaises(ValueError): self.verify()
    for mode in ('missing', 'duplicate', 'failed', 'escape'):
      with self.subTest(mode=mode):
        report = copy.deepcopy(self.report)
        if mode == 'missing': report['commands'].pop()
        elif mode == 'duplicate': report['commands'].append(report['commands'][0])
        elif mode == 'failed': report['commands'][0]['exit_code'] = 1
        else: report['commands'][0]['log'] = '../outside.log'
        with self.assertRaises(ValueError): self.verify(report)

  def test_compiler_alias_preserves_cache_and_output_configuration(self):
    compiler = self.root / 'compiler'; compiler.write_text('same compiler')
    alias = self.root / 'alias'; alias.symlink_to(compiler)
    (self.root / 'CMakeCache.txt').write_text('CMAKE_CXX_COMPILER:FILEPATH=' + str(alias) + '\n')
    with patch.object(quality.validate.shutil, 'which', return_value=str(compiler)):
      self.assertEqual(quality.validate.selected_compiler(self.root, 'CMAKE_CXX_COMPILER', 'c++'), str(alias))
    other = self.root / 'different'; other.write_text('different compiler')
    with patch.object(quality.validate.shutil, 'which', return_value=str(other)):
      with self.assertRaises(RuntimeError):
        quality.validate.selected_compiler(self.root, 'CMAKE_CXX_COMPILER', 'c++')

  def test_modified_or_missing_log_rejected(self):
    log = self.root / self.report['commands'][0]['log']
    log.write_text('altered')
    with self.assertRaises(ValueError): self.verify()
    log.unlink()
    with self.assertRaises(OSError): self.verify()

  def test_skipped_or_short_suite_rejected_even_with_matching_hash(self):
    command = next(c for c in self.report['commands'] if c['name'] == 'python-integration')
    log = self.root / command['log']
    for text in ('\nRan 72 tests in 1s\n\nOK (skipped=1)\n',
                 '\nRan 1 tests in 1s\n\nOK\n', '\nRan 72 tests in 1s\n\nFAILED\n'):
      log.write_text(text); command['sha256'] = quality.validate.sha(log)
      with self.assertRaises(ValueError): self.verify()

  def test_cli_rejects_failed_evidence(self):
    self.report['passed'] = False
    path = self.root / 'report.json'
    path.write_text(json.dumps(self.report))
    result = subprocess.run([sys.executable, str(Path(quality.__file__)), 'verify',
                             '--output', str(self.root)], capture_output=True)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn(b'No passing current-schema acceptance', result.stderr)

  def test_run_propagates_validator_failure(self):
    argv = ['quality', 'run', '--output', str(self.root), '--build-root', str(self.root / 'build')]
    with patch.object(sys, 'argv', argv), patch.object(quality.subprocess, 'run',
        side_effect=subprocess.CalledProcessError(1, ['validator'])):
      self.assertEqual(quality.main(), 1)


if __name__ == '__main__':
  unittest.main()
