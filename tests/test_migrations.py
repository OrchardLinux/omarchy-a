"""Migrations: run once each, in order, recorded; the move to the package; what omarchy-update says."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
BIN = PROJECT / 'desktop/shell/bin'
MIGRATIONS = PROJECT / 'desktop/shell/migrations'


def run(argv, home, omarchy, **env):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30,
                          env={'PATH': f'{BIN}:{os.environ["PATH"]}', 'HOME': str(home), 'OMARCHY_PATH': str(omarchy),
                               'OMARCHY_PACMAN_LOCK': str(home / 'no-lock'), **env})


@unittest.skipUnless(shutil.which('bash'), 'bash is required')
class Migrate(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home, self.omarchy = self.root / 'home', self.root / 'omarchy'
        self.home.mkdir()
        (self.omarchy / 'migrations').mkdir(parents=True)
        for name in ('200.sh', '100.sh'):
            (self.omarchy / 'migrations' / name).write_text(f'echo {name} >> "$HOME/ran"\n')

    def migrate(self, *args, **env):
        return run([str(BIN / 'omarchy-migrate'), *args], self.home, self.omarchy, **env)

    def test_each_runs_once_in_order_and_is_recorded(self):
        self.assertEqual(self.migrate('--pending').stdout, '100.sh\n200.sh\n')
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home / 'ran').read_text(), '100.sh\n200.sh\n')
        self.assertEqual(sorted(p.name for p in (self.home / '.local/state/omarchy/migrations').iterdir()),
                         ['100.sh', '200.sh'])
        self.migrate()
        self.assertEqual((self.home / 'ran').read_text(), '100.sh\n200.sh\n')
        self.assertEqual(self.migrate('--pending').returncode, 1)

    def test_a_failing_migration_stops_and_is_tried_again(self):
        (self.omarchy / 'migrations/150.sh').write_text('false\n')
        self.assertNotEqual(self.migrate().returncode, 0)
        self.assertEqual((self.home / 'ran').read_text(), '100.sh\n')
        self.assertEqual(self.migrate('--pending').stdout, '150.sh\n200.sh\n')

    def test_the_login_leaves_a_running_update_to_finish(self):
        (self.home / 'lock').touch()
        result = self.migrate(OMARCHY_PACMAN_LOCK=str(self.home / 'lock'), OMARCHY_MIGRATE_LOCK_WAIT='0')
        self.assertEqual(result.returncode, 0)
        self.assertIn('next login', result.stdout)
        self.assertFalse((self.home / 'ran').exists())

    def test_the_login_runs_them_before_the_desktop_starts(self):
        session = (PROJECT / 'desktop/configuration/login-session').read_text()
        self.assertIn('OMARCHY_MIGRATE_LOCK_WAIT=0 timeout 120 omarchy-migrate', session)
        self.assertLess(session.index('omarchy-migrate'), session.index('arch-ipad-first-theme'))
        self.assertLess(session.index('omarchy-migrate'), session.index('/usr/bin/labwc -m'))


class Shipped(unittest.TestCase):
    def test_migrations_are_named_by_time_and_newest_last(self):
        names = sorted(p.name for p in MIGRATIONS.iterdir())
        self.assertTrue(names)
        for name in names:
            self.assertRegex(name, r'^\d{10}\.sh$')
            # A migration changes the user's files; root's part is the package's install script.
            self.assertNotRegex((MIGRATIONS / name).read_text(), r'(?m)^\s*sudo\b')


@unittest.skipUnless(shutil.which('bash') and shutil.which('pgrep'), 'bash and pgrep are required')
class MoveToThePackage(unittest.TestCase):
    """1794908306.sh on a home the image made before the package."""
    def test_an_old_home_runs_the_packaged_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, omarchy = root / 'home', root / 'omarchy'
            (omarchy / 'config/labwc').mkdir(parents=True)
            shutil.copy(PROJECT / 'desktop/configuration/labwc-autostart', omarchy / 'config/labwc/autostart')
            (omarchy / 'applications').mkdir()
            (omarchy / 'applications/foot.desktop').write_text('[Desktop Entry]\n')
            old = home / '.local/share/omarchy-ipad'
            (old / 'bin').mkdir(parents=True)
            (home / '.config/labwc').mkdir(parents=True)
            (home / '.config/fontconfig').mkdir(parents=True)
            (home / '.config/labwc/autostart').write_text(
                'export OMARCHY_PATH="$HOME/.local/share/omarchy-ipad"\n/usr/local/libexec/arch-ipad-scale-output\n')
            (home / '.config/fontconfig/fonts.conf').write_text(
                '<dir prefix="xdg">omarchy-ipad/default/fonts/omarchy</dir>\n')
            result = run(['bash', '-euo', 'pipefail', str(MIGRATIONS / '1794908306.sh')], home, omarchy)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            autostart = (home / '.config/labwc/autostart').read_text()
            self.assertIn('. /usr/share/omarchy/default/labwc/autostart', autostart)
            # The old one is kept, as upstream's omarchy-refresh-config does.
            self.assertEqual(len(list((home / '.config/labwc').glob('autostart.bak.*'))), 1)
            self.assertEqual((home / '.config/fontconfig/fonts.conf').read_text(),
                             '<dir prefix="xdg">omarchy/default/fonts/omarchy</dir>\n')
            self.assertTrue((home / '.local/share/applications/foot.desktop').is_file())
            self.assertFalse(old.exists())

    def test_a_users_own_autostart_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, omarchy = root / 'home', root / 'omarchy'
            (home / '.config/labwc').mkdir(parents=True)
            (home / '.local/share/applications').mkdir(parents=True)
            (home / '.local/share/applications/foot.desktop').write_text('mine')
            (home / '.config/labwc/autostart').write_text('. /usr/share/omarchy/default/labwc/autostart\nmine\n')
            omarchy.mkdir()
            result = run(['bash', '-euo', 'pipefail', str(MIGRATIONS / '1794908306.sh')], home, omarchy)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('mine', (home / '.config/labwc/autostart').read_text())
            self.assertEqual((home / '.local/share/applications/foot.desktop').read_text(), 'mine')
            self.assertFalse(list((home / '.config/labwc').glob('autostart.bak.*')))


@unittest.skipUnless(shutil.which('bash'), 'bash is required')
class UpdateRestart(unittest.TestCase):
    def restart(self, *args, owned=False, kernel='6.12.0', state=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stubs = root / 'bin'
            stubs.mkdir()
            (stubs / 'uname').write_text('#!/bin/sh\necho 6.12.0\n')
            (stubs / 'pacman').write_text('#!/bin/sh\n' + ('exit 0' if owned else 'exit 1') + '\n')
            for stub in stubs.iterdir():
                stub.chmod(0o755)
            modules = root / 'modules' / kernel
            modules.mkdir(parents=True)
            (modules / 'modules.builtin').touch()
            if state:
                (root / '.local/state/omarchy').mkdir(parents=True)
                (root / '.local/state/omarchy/reboot-required').touch()
            return subprocess.run(['bash', str(BIN / 'omarchy-update-restart'), *args], capture_output=True, text=True,
                                  env={'PATH': f'{stubs}:{os.environ["PATH"]}', 'HOME': str(root),
                                       'OMARCHY_KERNEL_MODULES_PATH': str(root / 'modules')}).stdout

    def test_what_an_update_needs_before_it_takes_effect(self):
        self.assertIn('up to date', self.restart('omarchy-a 1-1', 'omarchy-a 1-1'))
        self.assertIn('Log out and back in', self.restart('omarchy-a 1-1', 'omarchy-a 2-1'))
        # A kernel from orchard's platform layer is no package: no update changed it.
        self.assertNotIn('kernel', self.restart('a', 'a', kernel='6.13.0'))
        self.assertIn('new kernel', self.restart('a', 'a', owned=True, kernel='6.13.0'))
        self.assertNotIn('kernel', self.restart('a', 'a', owned=True))
        self.assertIn('orchard launch', self.restart('a', 'a', state=True))

    def test_update_upgrades_then_migrates(self):
        update = (BIN / 'omarchy-update').read_text()
        self.assertLess(update.index('omarchy-update-system-pkgs'), update.index('omarchy-migrate'))
        self.assertIn('-Syu', (BIN / 'omarchy-update-system-pkgs').read_text())
        self.assertIn('exec omarchy-update "$@"', (BIN / 'omarchy').read_text())
        # The menu's Update > Omarchy runs it through upstream's terminal launcher, which is here.
        menu = (PROJECT / 'desktop/shell/default/omarchy/omarchy-menu.jsonc').read_text()
        self.assertIn('"action":"omarchy-launch-floating-terminal-with-presentation omarchy-update"', menu)
        launcher = (BIN / 'omarchy-launch-floating-terminal-with-presentation').read_text()
        self.assertIn('foot', launcher)
        for name in ('omarchy-launch-floating-terminal-with-presentation', 'omarchy-update', 'omarchy-update-lock', 'omarchy-update-pacman', 'omarchy-update-confirm',
                     'omarchy-update-system-pkgs', 'omarchy-update-restart', 'omarchy-migrate',
                     'omarchy-refresh-config', 'omarchy-dev-add-migration'):
            self.assertTrue(os.access(BIN / name, os.X_OK), name)
            self.assertRegex((BIN / name).read_text(), r'(?m)^# omarchy:summary=', name)


if __name__ == '__main__':
    unittest.main()
