"""Readiness is a read-only policy check, never a speculative PM transition."""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'system/overlay/usr/local/bin/ipadlinux-suspend-ready'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ready = load('suspend_ready', HELPER)
powerd = load('suspend_ready_powerd', ROOT / 'system/overlay/usr/libexec/omarchy-powerd')


class SuspendReady(unittest.TestCase):
    def invoke(self, identity, argv=(), readiness=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'compatible'
            query = Path(directory) / 'suspend_ready'
            if identity is not None:
                path.write_bytes(identity)
            if readiness is not None:
                query.write_bytes(readiness)
            out, err = io.StringIO(), io.StringIO()
            with patch.object(ready, 'qualification', return_value=None), patch.object(ready, 'COMPATIBLE', path), patch.object(ready, 'READINESS', query), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ready.main(argv)
            if identity is not None:
                self.assertEqual(path.read_bytes(), identity)
            if readiness is not None:
                self.assertEqual(query.read_bytes(), readiness)
            return code, out.getvalue(), err.getvalue()

    def test_qualification_precedes_identity_and_kernel_admission(self):
        with patch.object(ready, 'qualification', return_value='not qualified'), \
                patch.object(ready, 'refusal') as admission, \
                patch.object(ready.Path, 'read_bytes') as identity, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ready.main([]), 1)
            self.assertIn('not qualified', err.getvalue())
            identity.assert_not_called()
            admission.assert_not_called()

    def test_qualification_uses_public_helper_and_fails_closed(self):
        with patch.object(ready.subprocess, 'run') as run:
            for status in (0, 1, 2):
                run.return_value = subprocess.CompletedProcess([], status)
                self.assertEqual(ready.qualification() is None, status == 0)
            run.assert_called_with(['/usr/lib/orchard/device-feature', 'suspend', 'working'],
                                   capture_output=True, text=True, timeout=5)
            for error in (FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired('helper', 5)):
                run.side_effect = error
                self.assertIn('cannot verify', ready.qualification())

    def test_systemd_direct_suspend_uses_same_gate(self):
        from release.public_root import system_files
        dropin = 'etc/systemd/system/systemd-suspend.service.d/60-omarchy-a-qualification.conf'
        data, mode = system_files()[dropin]
        self.assertIn(b'ExecStartPre=/usr/local/bin/ipadlinux-suspend-ready', data)
        self.assertEqual(mode, 0o644)
        logind = system_files()['etc/systemd/logind.conf.d/60-omarchy-a-power.conf'][0].decode()
        for setting in ('HandlePowerKey', 'HandleSuspendKey', 'HandleHibernateKey',
                        'HandleLidSwitch', 'HandleLidSwitchExternalPower', 'HandleLidSwitchDocked', 'IdleAction'):
            self.assertIn(setting + '=ignore', logind)

    def test_j71t_refuses_without_an_admission_query(self):
        for identity in (b'apple,j71t\0apple,s8003\0', b'apple,j71t\0apple,s8000\0'):
            code, out, err = self.invoke(identity)
            self.assertEqual((code, out), (1, ''))
            self.assertIn('no suspend readiness query', err)
            self.assertIn('GPU/VXD/SEP', err)

    def test_j71t_follows_the_kernel_admission_query(self):
        identity = b'apple,j71t\0apple,s8003\0'
        self.assertEqual(self.invoke(identity, readiness=b'ready\n'), (0, '', ''))
        code, out, err = self.invoke(identity, readiness=b'not-ready 201000000.gpu -16\n')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('refused by 201000000.gpu (-16)', err)
        code, _, err = self.invoke(identity, readiness=b'not-ready apple_h9p_sleep_precheck -16\n')
        self.assertEqual(code, 1)
        self.assertIn('apple_h9p_sleep_precheck', err)

    def test_j71t_malformed_kernel_answer_fails_closed(self):
        for answer in (b'', b'readyish\n', b'not-ready\n', b'\xff\n'):
            code, out, err = self.invoke(b'apple,j71t\0', readiness=answer)
            self.assertEqual((code, out), (1, ''))
            self.assertIn('Suspend unavailable:', err)

    def test_other_boards_ignore_the_kernel_query(self):
        self.assertEqual(self.invoke(b'apple,j71b\0', readiness=b'not-ready x -16\n'), (0, '', ''))

    def test_other_boards_keep_logind_and_kernel_path(self):
        for board in (b'apple,j71b', b'apple,j72b', b'apple,j71s', b'raspberrypi,4-model-b'):
            self.assertEqual(self.invoke(board + b'\0apple,arm-platform\0'), (0, '', ''))

    def test_compatible_is_an_exact_nul_delimited_match(self):
        self.assertEqual(self.invoke(b'apple,j71t-extra\0'), (0, '', ''))
        self.assertEqual(self.invoke(b'apple,s8003\0apple,j71t\0')[0], 1)

    def test_missing_or_malformed_identity_fails_closed(self):
        for identity in (None, b'', b'apple,j71t'):
            code, out, err = self.invoke(identity)
            self.assertEqual((code, out), (1, ''))
            self.assertIn('Suspend unavailable:', err)

    def test_no_force_or_alternate_sysfs_option(self):
        self.assertEqual(self.invoke(b'apple,j71t\0', ['--force'])[0], 2)
        result = subprocess.run([sys.executable, str(HELPER), '--force'], capture_output=True, text=True, timeout=2)
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertIn('Usage:', result.stderr)

    def test_refresh_ships_executable_helper(self):
        from release.public_root import system_files
        self.assertEqual(system_files()['usr/local/bin/ipadlinux-suspend-ready'], (HELPER.read_bytes(), 0o755))
        self.assertEqual(HELPER.stat().st_mode & 0o777, 0o755)

    def test_daemon_uses_exit_status_and_logs_reason(self):
        messages = []
        with patch.object(powerd.Path, 'exists', return_value=True), patch.object(powerd, 'log', messages.append), patch.object(powerd, 'command') as command:
            command.return_value = subprocess.CompletedProcess([], 1, '', 'Suspend unavailable: reason\n')
            self.assertFalse(powerd.platform_suspend_ready())
            self.assertIn('reason', messages[-1])
            command.assert_called_once_with('/usr/local/bin/ipadlinux-suspend-ready')
            command.return_value = subprocess.CompletedProcess([], 0, '', '')
            self.assertTrue(powerd.platform_suspend_ready())

    def test_daemon_refuses_missing_helper(self):
        with patch.object(powerd.Path, 'exists', return_value=False), patch.object(powerd, 'log'), patch.object(powerd, 'command') as command:
            self.assertFalse(powerd.platform_suspend_ready())
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
