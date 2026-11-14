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
    def invoke(self, readiness=None, argv=()):
        with tempfile.TemporaryDirectory() as directory:
            query = Path(directory) / 'suspend_ready'
            if readiness is not None:
                query.write_bytes(readiness)
            out, err = io.StringIO(), io.StringIO()
            with patch.object(ready, 'READINESS', query), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ready.main(argv)
            if readiness is not None:
                self.assertEqual(query.read_bytes(), readiness)
            return code, out.getvalue(), err.getvalue()

    def test_no_feature_table_or_board_identity(self):
        source = HELPER.read_text()
        for name in ('device-feature', 'devicetree', 'compatible', 'subprocess'):
            self.assertNotIn(name, source)

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

    def test_refuses_without_an_admission_query(self):
        code, out, err = self.invoke()
        self.assertEqual((code, out), (1, ''))
        self.assertIn('no suspend readiness query', err)

    def test_follows_the_kernel_admission_query(self):
        self.assertEqual(self.invoke(b'ready\n'), (0, '', ''))
        code, out, err = self.invoke(b'not-ready 201000000.gpu -16\n')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('refused by 201000000.gpu (-16)', err)
        code, _, err = self.invoke(b'not-ready apple_h9p_sleep_precheck -16\n')
        self.assertEqual(code, 1)
        self.assertIn('apple_h9p_sleep_precheck', err)
        code, _, err = self.invoke(b'not-ready transition -16\n')
        self.assertEqual(code, 1)
        self.assertIn('refused by transition', err)

    def test_malformed_kernel_answer_fails_closed(self):
        for answer in (b'', b'readyish\n', b'not-ready\n', b'\xff\n'):
            code, out, err = self.invoke(answer)
            self.assertEqual((code, out), (1, ''))
            self.assertIn('Suspend unavailable:', err)

    def test_unreadable_answer_fails_closed(self):
        with patch.object(ready.Path, 'read_text', side_effect=PermissionError('denied')), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ready.main([]), 1)
        self.assertIn('cannot read kernel suspend readiness', err.getvalue())

    def test_no_force_or_alternate_sysfs_option(self):
        self.assertEqual(self.invoke(b'ready\n', ['--force'])[0], 2)
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
