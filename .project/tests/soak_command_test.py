"""Real Linux process ownership and signal tests for the prepared long-run gate."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

# 2026-09-13: canonical test location after staged native preflight.
# ROOT = Path(__file__).resolve().parents[4]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.project/checks'))
import performance_regression as runner


class CommandOwnershipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != 'linux':
            raise RuntimeError('These process ownership tests require Linux; no skipped substitute')
        cls.libc = ctypes.CDLL(None, use_errno=True)
        cls.previous_subreaper = ctypes.c_int()
        if cls.libc.prctl(37, ctypes.byref(cls.previous_subreaper), 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'Cannot read test-process subreaper state')
        if cls.libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'Cannot adopt and reap test grandchildren')

    @classmethod
    def tearDownClass(cls):
        if cls.libc.prctl(36, cls.previous_subreaper.value, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'Cannot restore test-process subreaper state')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='football-command-test-')
        self.output = Path(self.temporary.name)
        self.commands, self.processes, self.reaped_children = [], [], set()
        self.signal_at_creation = False
        self.initial_mask = signal.pthread_sigmask(signal.SIG_BLOCK, [])
        self.previous_handler = signal.signal(signal.SIGTERM, runner.interrupt_command)
        real_popen = subprocess.Popen

        def capture(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            self.processes.append(process)
            if self.signal_at_creation:
                # Actual child creation succeeded, but the caller has not yet
                # received its handle. The signal must be deferred until then.
                os.kill(os.getpid(), signal.SIGTERM)
            return process

        self.popen_patch = mock.patch.object(runner.subprocess, 'Popen', side_effect=capture)
        self.popen_patch.start()

    def tearDown(self):
        self.popen_patch.stop()
        for process in self.processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        record = self.output / 'tree.json'
        if record.exists():
            child = json.loads(record.read_text())['child']
            if child not in self.reaped_children:
                # A test-only subreaper owns this specific PID after the group
                # leader exits. Never signal an unrelated or already-reaped PID.
                found, _ = os.waitpid(child, os.WNOHANG)
                if found == 0:
                    os.kill(child, signal.SIGKILL)
                    os.waitpid(child, 0)
        signal.pthread_sigmask(signal.SIG_SETMASK, self.initial_mask)
        signal.signal(signal.SIGTERM, self.previous_handler)
        self.temporary.cleanup()

    def run_python(self, source, timeout=5):
        return runner.run_command([sys.executable, '-c', source], 'command',
                                  output=self.output, commands=self.commands,
                                  environment=dict(os.environ), timeout=timeout)

    def terminal(self):
        saved = json.loads((self.output / 'commands.json').read_text())
        self.assertEqual(saved, self.commands)
        self.assertEqual(len(saved), 1)
        row = saved[0]
        self.assertEqual(row['state'], 'finished')
        data = (self.output / row['log']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), row['log_sha256'])
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, []), self.initial_mask)
        return row

    def process_tree(self, interrupt=False):
        return (
            'import subprocess,sys,os,json,time,signal\n'
            'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"])\n'
            f'open({str(self.output / "tree.json")!r},"w").write(json.dumps(dict(parent=os.getpid(),child=child.pid)))\n'
            'print("tree-started",flush=True)\n' +
            (f'time.sleep(.05);os.kill({os.getpid()},signal.SIGTERM)\n' if interrupt else '') +
            'time.sleep(60)\n')

    def assert_tree_killed(self):
        tree = json.loads((self.output / 'tree.json').read_text())
        self.assertEqual(tree['parent'], self.commands[0]['pid'])
        self.assertEqual(self.processes[0].returncode, -signal.SIGKILL)
        limit = time.monotonic() + 5
        while time.monotonic() < limit:
            pid, status = os.waitpid(tree['child'], os.WNOHANG)
            if pid:
                self.reaped_children.add(pid)
                self.assertTrue(os.WIFSIGNALED(status))
                self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
                return
            time.sleep(.01)
        self.fail('Owned grandchild survived process-group cleanup')

    def test_success_retains_stdout_stderr_and_command_identity(self):
        text = self.run_python('import sys;print("stdout");print("stderr",file=sys.stderr)')
        self.assertIn('stdout', text)
        self.assertIn('stderr', text)
        row = self.terminal()
        self.assertEqual(row['returncode'], 0)
        self.assertFalse(row['timed_out'])
        self.assertEqual(row['launch_argv'][-3:], row['argv'])

    def test_nonzero_exit_retains_failure_output(self):
        with self.assertRaisesRegex(RuntimeError, 'command failed'):
            self.run_python('import sys;print("native-failure",flush=True);sys.exit(7)')
        self.assertEqual(self.terminal()['returncode'], 7)
        self.assertIn('native-failure', (self.output / 'command.log').read_text())

    def test_missing_target_is_a_failed_command(self):
        with self.assertRaisesRegex(RuntimeError, 'command failed'):
            runner.run_command([self.output / 'missing-target'], 'command', output=self.output,
                               commands=self.commands, environment=dict(os.environ))
        self.assertEqual(self.terminal()['returncode'], 127)

    def test_missing_launcher_retains_launch_failure(self):
        with mock.patch.object(runner, 'COMMAND_LAUNCHER', self.output / 'missing-launcher'):
            with self.assertRaises(FileNotFoundError):
                self.run_python('pass')
        row = self.terminal()
        self.assertIsNone(row['returncode'])
        self.assertEqual(row['error_type'], 'FileNotFoundError')

    def test_timeout_kills_and_reaps_owned_process_tree(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_python(self.process_tree(), timeout=2)
        self.assertTrue(self.terminal()['timed_out'])
        self.assert_tree_killed()
        self.assertIn('tree-started', (self.output / 'command.log').read_text())

    def test_sigterm_during_wait_kills_owned_process_tree(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_python(self.process_tree(interrupt=True))
        self.assertEqual(raised.exception.code, 128 + signal.SIGTERM)
        row = self.terminal()
        self.assertFalse(row['timed_out'])
        self.assertEqual(row['error_type'], 'SystemExit')
        self.assert_tree_killed()

    def test_sigterm_at_creation_does_not_orphan_the_new_child(self):
        self.signal_at_creation = True
        with self.assertRaises(SystemExit) as raised:
            self.run_python('import time;time.sleep(60)')
        self.assertEqual(raised.exception.code, 128 + signal.SIGTERM)
        self.assertEqual(self.terminal()['returncode'], -signal.SIGKILL)
        self.assertEqual(len(self.processes), 1)
        self.assertIsNotNone(self.processes[0].returncode)

    def test_temporary_signal_mask_is_not_inherited_by_command(self):
        value = self.run_python('import signal,json;print(json.dumps(sorted(int(s) for s in '
                                'signal.pthread_sigmask(signal.SIG_BLOCK,[]))))')
        self.assertEqual(json.loads(value), sorted(int(s) for s in self.initial_mask))
        self.terminal()

    def test_existing_log_cannot_be_overwritten(self):
        self.run_python('print("original-evidence")')
        before = (self.output / 'command.log').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'must be preserved'):
            self.run_python('print("replacement")')
        self.assertEqual(before, (self.output / 'command.log').read_bytes())
        self.terminal()


if __name__ == '__main__':
    unittest.main()
