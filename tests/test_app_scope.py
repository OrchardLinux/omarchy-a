"""uwsm-app: every app in its own systemd user scope, and started without one too."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'desktop/shell/bin/uwsm-app'
# Stand-in for systemd-run --scope: records its arguments, then becomes the command.
SYSTEMD_RUN = '''#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
[ -z "$SCOPE_FAILS" ] || exit 1
while [ "$1" != "--" ]; do shift; done
shift
exec "$@"
'''


class AppScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        stubs, runtime = root / 'bin', root / 'run'
        stubs.mkdir()
        runtime.mkdir()
        stub = stubs / 'systemd-run'
        stub.write_text(SYSTEMD_RUN)
        stub.chmod(0o755)
        self.calls, self.started = root / 'calls', root / 'started'
        self.env = {**os.environ, 'PATH': '%s:%s' % (stubs, os.environ['PATH']), 'XDG_RUNTIME_DIR': str(runtime),
                    'CALLS': str(self.calls), 'STARTED': str(self.started)}

    def renderer_seen(self, **env):
        """QT_QUICK_BACKEND as an app started by uwsm-app finds it."""
        seen = Path(self.temp.name) / 'seen'
        subprocess.run(['bash', str(SCRIPT), '--', 'sh', '-c', 'echo "${QT_QUICK_BACKEND:-unset}" > "$1"', 'sh', str(seen)],
                       env={**self.env, **env}, capture_output=True, text=True, timeout=20)
        deadline = time.monotonic() + 5
        while not seen.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)
        return seen.read_text().strip()

    def test_apps_draw_on_the_gpu_where_the_desktop_does(self):
        # The shell's software renderer is its own: on a GPU desktop the apps
        # it starts don't inherit it; on the software desktop they do.
        self.assertEqual(self.renderer_seen(QT_QUICK_BACKEND='software', WLR_RENDERER='gles2'), 'unset')
        self.assertEqual(self.renderer_seen(QT_QUICK_BACKEND='software', WLR_RENDERER='pixman'), 'software')

    def launch(self, *options, **env):
        result = subprocess.run(['bash', str(SCRIPT), *options, '--', 'sh', '-c', 'echo "$1" >> "$STARTED"', 'sh', 'app'],
                                env={**self.env, **env}, capture_output=True, text=True, timeout=20)
        # In a scope the app outlives the launcher, which returns once it has started.
        deadline = time.monotonic() + 5
        while not self.started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)
        return result

    def test_app_runs_once_in_a_scope_named_after_its_desktop_id(self):
        result = self.launch('-a', 'org.kde.dolphin-beta')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.started.read_text(), 'app\n')
        call = self.calls.read_text()
        self.assertRegex(call, r'^--user --scope .*--slice=app\.slice '
                               r'--unit=app-org\.kde\.dolphin\\x2dbeta-[0-9a-f]{8}\.scope -- ')

    def test_scope_is_named_after_the_command_without_an_id(self):
        self.launch()
        self.assertRegex(self.calls.read_text(), r'--unit=app-sh-[0-9a-f]{8}\.scope ')

    def test_app_still_starts_once_when_the_scope_cannot_be_made(self):
        result = self.launch(SCOPE_FAILS='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertEqual(self.started.read_text(), 'app\n')

    def test_app_starts_without_a_user_manager(self):
        env = {k: v for k, v in self.env.items() if k != 'XDG_RUNTIME_DIR'}
        subprocess.run(['bash', str(SCRIPT), '--', 'sh', '-c', 'echo app >> "$STARTED"'], env=env, check=True, timeout=20)
        self.assertEqual(self.started.read_text(), 'app\n')
        self.assertFalse(self.calls.exists())

    def test_the_launcher_and_the_app_shortcuts_start_apps_through_it(self):
        library = (PROJECT / 'desktop/shell/shell/services/AppLibrary.qml').read_text()
        self.assertIn('["uwsm-app", "-a", id, "--"].concat(command)', library)
        focus = (PROJECT / 'desktop/shell/bin/omarchy-launch-or-focus').read_text()
        self.assertIn('uwsm-app -- $WINDOW_PATTERN', focus)
        self.assertIn('shell focusWindow', focus)
        self.assertIn('function focusWindow(pattern: string): string', (PROJECT / 'desktop/shell/shell/shell.qml').read_text())


if __name__ == '__main__':
    unittest.main()
