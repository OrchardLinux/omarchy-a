import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
BIN = PROJECT / 'desktop/shell/bin'
MENU = PROJECT / 'desktop/shell/default/omarchy/omarchy-menu.jsonc'

LOG = 'printf "%s\\n" "${0##*/} $*" >> "$CALL_LOG"\n'
# Strip the wrapper's own options, then run what it wraps.
WRAPPER = LOG + 'while [ "${1#--}" != "$1" ]; do shift; done\nexec "$@"\n'
STUBS = {
    'systemd-run': WRAPPER,
    'systemd-inhibit': WRAPPER,
    'timeout': LOG + 'shift\nexec "$@"\n',
    'omarchy-i18n': 'printf "%s" "$1"\n',
    'omarchy-osd': LOG,
    'omarchy-state': LOG,
    'omarchy-notification-send': LOG,
    'omarchy-hyprland-window-close-all': LOG + 'exit "${CLOSE_STATUS:-0}"\n',
    'labwc': LOG + 'exit "${TEST_STATUS:-0}"\n',
    'systemctl': LOG + 'exit "${TEST_STATUS:-0}"\n',
}


def menu_action(name):
    entry = re.search(r'"system\.' + name + r'":\s*(\{[^\n]+\})', MENU.read_text())
    return json.loads(entry.group(1))['action']


class MenuShutdownTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.log = self.root / 'calls'
        for name, body in STUBS.items():
            self.stub(name, body)
        (self.root / 'omarchy-system').symlink_to(BIN / 'omarchy-system')

    def stub(self, name, body):
        command = self.root / name
        command.write_text('#!/bin/sh\n' + body)
        command.chmod(0o755)

    def run_action(self, action, **extra):
        self.log.write_text('')
        env = {**os.environ, 'PATH': str(self.root), 'CALL_LOG': str(self.log), **extra}
        result = subprocess.run(['/bin/bash', '-c', action], env=env,
                                capture_output=True, text=True, timeout=10)
        return result, self.log.read_text().splitlines()

    def test_menu_keeps_upstreams_calls(self):
        for name, action in (('logout', 'omarchy-system logout'),
                             ('reboot', 'omarchy-system reboot'),
                             ('shutdown', 'omarchy-system shutdown'),
                             ('lock', 'omarchy-system-lock')):
            self.assertEqual(menu_action(name), action)

    def test_commands_are_shipped(self):
        for name in ('omarchy-system', 'omarchy-system-lock', 'omarchy-system-wake', 'omarchy-osd',
                     'omarchy-i18n', 'omarchy-state', 'omarchy-notification-send',
                     'omarchy-hyprland-window-close-all'):
            self.assertTrue(os.access(BIN / name, os.X_OK), name)

    def test_logout_shows_osd_closes_windows_then_ends_the_compositor(self):
        # login-session execs labwc, so its exit ends the session and greetd
        # brings the greeter back. Upstream's uwsm stop has no session here.
        result, calls = self.run_action(menu_action('logout'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--setenv=LABWC_PID', calls[0])
        self.assertEqual(calls[1:], ['omarchy-osd -i logout -m system.loggingOut -d 5000',
                                     'timeout 2s omarchy-hyprland-window-close-all --wait',
                                     'omarchy-hyprland-window-close-all --wait',
                                     'labwc --exit'])

    def test_reboot_requests_normal_system_reboot(self):
        result, calls = self.run_action(menu_action('reboot'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1], 'systemctl reboot --no-wall')

    def test_shutdown_requests_normal_system_poweroff(self):
        result, calls = self.run_action(menu_action('shutdown'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call.startswith('systemd-inhibit ') for call in calls), calls)
        self.assertEqual(calls[-1], 'systemctl poweroff --no-wall')

    def test_failure_is_notified_and_returned(self):
        for name, verb in (('logout', 'labwc --exit'), ('reboot', 'systemctl reboot --no-wall'),
                           ('shutdown', 'systemctl poweroff --no-wall')):
            with self.subTest(name):
                result, calls = self.run_action(menu_action(name), TEST_STATUS='1')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(calls[-2], verb)
                self.assertTrue(calls[-1].startswith('omarchy-notification-send -u critical system.'), calls)

    def test_a_window_that_will_not_close_does_not_block_the_exit(self):
        result, calls = self.run_action(menu_action('logout'), CLOSE_STATUS='124')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1], 'labwc --exit')

    def test_failure_messages_are_in_the_catalog(self):
        catalog = json.loads((PROJECT / 'desktop/shell/default/i18n/en/cli.json').read_text())
        used = set(re.findall(r'omarchy-i18n (system\.\w+)', (BIN / 'omarchy-system').read_text()))
        self.assertEqual(len(used), 9)
        self.assertLessEqual(used, set(catalog))

    def test_the_real_i18n_command_reads_the_shipped_catalog(self):
        bash = shutil.which('bash')
        probe = subprocess.run([bash, '-c', 'help mapfile'], capture_output=True)
        if probe.returncode != 0 or not shutil.which('jq'):
            self.skipTest('needs bash with mapfile, and jq')
        env = {**os.environ, 'OMARCHY_PATH': str(PROJECT / 'desktop/shell'),
               'OMARCHY_LANGUAGE_FILE': '/nonexistent'}
        result = subprocess.run([bash, str(BIN / 'omarchy-i18n'), 'system.loggingOut'], env=env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stdout, 'Logging out')


class WindowCloseAllTests(unittest.TestCase):
    def run_close_all(self, shell_status, *args):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / 'calls'
            remaining = root / 'remaining'
            remaining.write_text('2')
            shell = root / 'omarchy-shell'
            shell.write_text('#!/bin/sh\nprintf "%s\\n" "$2" >> "$CALL_LOG"\n'
                             '[ "$SHELL_STATUS" = 0 ] || exit "$SHELL_STATUS"\n'
                             'if [ "$2" = windowCount ]; then\n'
                             '  read -r n < "$REMAINING"; echo "$n"\n'
                             '  case "$n" in 2) echo 1;; *) echo 0;; esac > "$REMAINING"\n'
                             'fi\n')
            sleep = root / 'sleep'
            sleep.write_text('#!/bin/sh\n')
            shell.chmod(0o755)
            sleep.chmod(0o755)
            env = {**os.environ, 'PATH': str(root), 'CALL_LOG': str(log), 'REMAINING': str(remaining),
                   'SHELL_STATUS': str(shell_status)}
            result = subprocess.run([str(BIN / 'omarchy-hyprland-window-close-all'), *args], env=env,
                                    capture_output=True, text=True, timeout=5)
            return result, log.read_text().split()

    def test_wait_ends_when_the_windows_are_gone(self):
        result, calls = self.run_close_all(0, '--wait')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['closeAllWindows', 'windowCount', 'windowCount', 'windowCount'])

    def test_without_wait_it_only_closes(self):
        result, calls = self.run_close_all(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['closeAllWindows'])

    def test_no_shell_is_a_failure(self):
        result, calls = self.run_close_all(1, '--wait')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, ['closeAllWindows'])

    def test_the_shell_answers_both_calls(self):
        shell = (PROJECT / 'desktop/shell/shell/shell.qml').read_text()
        self.assertIn('function closeAllWindows(): string', shell)
        self.assertIn('function windowCount(): string', shell)
        library = (PROJECT / 'desktop/shell/shell/services/AppLibrary.qml').read_text()
        self.assertIn('function closeAllToplevels()', library)


class PowerOwnerTests(unittest.TestCase):
    def test_lock_and_wake_only_feed_omarchy_powerd(self):
        # docs/power-and-lock.md: one owner of the lock, the screen and sleep.
        for name, verb in (('omarchy-system-lock', 'idle'), ('omarchy-system-wake', 'wake')):
            lines = (BIN / name).read_text().splitlines()
            code = [line for line in lines if line and not line.startswith('#')]
            self.assertEqual(code, ['exec /usr/libexec/omarchy-powerctl %s >/dev/null' % verb])


if __name__ == '__main__':
    unittest.main()
