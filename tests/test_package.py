"""The omarchy-a package: what it holds, its version, its dependencies, and what its install does."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from release import audit, package
from package_tree import elf, mode, tree

PROJECT = Path(__file__).resolve().parents[1]
HOOK = PROJECT / 'system/overlay/usr/share/libalpm/hooks/omarchy-a-etc-overrides.hook'
OVERRIDE_SCRIPT = PROJECT / 'system/overlay/usr/share/libalpm/scripts/omarchy-a-etc-overrides'
INSTALL = PROJECT / 'system/overlay/usr/lib/omarchy-a/package-install'


OVERRIDES = ('etc/os-release', 'etc/bluetooth/main.conf')


@unittest.skipUnless(shutil.which('bash'), 'bash runs desktop/install-tree')
class Contents(unittest.TestCase):
    def test_the_package_is_the_payload_the_helpers_and_the_overlay(self):
        root = tree()
        self.assertEqual(os.readlink(root / 'usr/bin/omarchy-update'), '/usr/share/omarchy/bin/omarchy-update')
        self.assertEqual(mode(root / 'usr/libexec/omarchy-wtype'), 0o755)
        self.assertTrue((root / 'usr/lib/omarchy-bluetooth/dbus_next/__init__.py').is_file())
        self.assertEqual(mode(root / 'etc/sudoers.d/90-tablet'), 0o440)
        self.assertEqual(mode(root / 'usr/libexec/omarchy-powerd'), 0o755)
        self.assertEqual(mode(root / 'usr/share/libalpm/scripts/omarchy-a-etc-overrides'), 0o755)
        self.assertEqual(mode(root / 'usr/lib/omarchy-a/package-install'), 0o755)
        self.assertTrue((root / 'usr/share/libalpm/hooks/omarchy-a-etc-overrides.hook').is_file())
        self.assertFalse((root / 'home').exists())

    def test_files_another_package_owns_go_to_the_overrides(self):
        root = tree()
        for name in OVERRIDES:
            with self.subTest(name=name):
                self.assertFalse((root / name).exists())
                self.assertEqual((root / 'usr/share/omarchy/etc-overrides' / name).read_bytes(),
                                 (PROJECT / 'system/overlay' / name).read_bytes())

    def test_skel_marks_exactly_the_shipped_migrations_done(self):
        root = tree()
        markers = root / 'etc/skel/.local/state/omarchy/migrations'
        self.assertEqual(sorted(p.name for p in markers.iterdir()),
                         sorted(p.name for p in (PROJECT / 'desktop/shell/migrations').glob('*.sh')))
        self.assertEqual(mode(root / 'etc/skel/.local'), 0o700)
        self.assertEqual(mode(root / 'etc/skel'), 0o755)

    def test_nothing_in_the_build_path_is_our_python(self):
        # The recipe runs make: the Makefile and install-tree are shell, and call no Python of ours.
        for path in (PROJECT / 'Makefile', PROJECT / 'desktop/install-tree'):
            self.assertNotIn('python', path.read_text().lower(), path.name)


class Version(unittest.TestCase):
    def test_the_version_is_the_last_release(self):
        with patch.dict(os.environ, {'OMARCHY_A_VERSION': ''}), \
                patch.object(package.subprocess, 'check_output', return_value='v0.3.1\n') as git:
            self.assertEqual(package.version(), '0.3.1')
        self.assertIn('--abbrev=0', git.call_args.args[0])

    def test_the_recipe_names_its_version(self):
        with patch.dict(os.environ, {'OMARCHY_A_VERSION': '0.4.0'}):
            self.assertEqual(package.version(), '0.4.0')
        with patch.dict(os.environ, {'OMARCHY_A_VERSION': '0.4.0-rc1'}):
            self.assertEqual(package.version(), '0.4.0.rc1')
        for bad in ('0.4:1', '.4', '0 4'):
            with self.subTest(bad=bad), patch.dict(os.environ, {'OMARCHY_A_VERSION': bad}), self.assertRaises(ValueError):
                package.version()

    def test_no_release_tag_is_an_error_not_a_low_version(self):
        error = subprocess.CalledProcessError(128, 'git')
        with patch.dict(os.environ, {'OMARCHY_A_VERSION': ''}), \
                patch.object(package.subprocess, 'check_output', side_effect=error), \
                self.assertRaisesRegex(ValueError, 'OMARCHY_A_VERSION'):
            package.version()


class Recipe(unittest.TestCase):
    """The recipe is the Orchard package repository's; an image build runs it on a tarball of its checkout."""
    RECIPE = ("pkgname=omarchy-a\npkgver=0.4.0\npkgrel=1\n_commit=abc123\n"
              "source=(\"omarchy-a-${_commit}.tar.gz::${url}/archive/${_commit}.tar.gz\"\n"
              "        \"wvkbd-0.20.tar.gz::https://example/wvkbd.tar.gz\")\n"
              "sha256sums=('abc'\n            'def')\nbuild() {\n  make\n}\n")

    def test_the_checkout_is_the_first_source(self):
        text = package.local_recipe(self.RECIPE, '0.3.1', 'f' * 64)
        self.assertIn('pkgver=0.3.1\n', text)
        self.assertIn('_commit=checkout\n', text)
        self.assertIn('source=("omarchy-a-${_commit}.tar.gz"\n        "wvkbd-0.20.tar.gz::https://example/wvkbd.tar.gz")', text)
        self.assertIn("sha256sums=('" + 'f' * 64 + "'\n            'def')", text)
        with self.assertRaisesRegex(ValueError, 'first'):
            package.local_recipe(self.RECIPE.replace("sha256sums=('abc'\n", "sha256sums=('abc' 'x'\n"), '0.3.1', 'f')

    def test_the_tarball_is_the_tree_as_a_release_has_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            for name in ('Makefile', 'desktop/install-tree', 'out/x', '.git/HEAD', 'desktop/__pycache__/a.pyc'):
                (project / name).parent.mkdir(parents=True, exist_ok=True)
                (project / name).write_text(name)
            package.tarball(root / 'a.tar.gz', project)
            import tarfile
            with tarfile.open(root / 'a.tar.gz') as archive:
                names = {member.name for member in archive if member.isfile()}
            self.assertEqual(names, {'omarchy-a-checkout/Makefile', 'omarchy-a-checkout/desktop/install-tree'})

    def test_the_recipe_comes_from_a_checkout_or_the_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'checkout').mkdir()
            for name in package.RECIPE_FILES:
                (root / 'checkout' / name).write_text(name)
            path = package.recipe(root / 'recipe', root / 'checkout')
            self.assertEqual(path.read_text(), 'PKGBUILD')
            self.assertEqual((root / 'recipe/omarchy-a.install').read_text(), 'omarchy-a.install')
        self.assertEqual(package.RECIPE_URL,
                         'https://raw.githubusercontent.com/OrchardLinux/packages/main/packages/omarchy-a/arch/')

    def test_only_the_base_is_the_images_own(self):
        self.assertEqual([line for line in (PROJECT / 'system/packages.txt').read_text().splitlines()
                          if line and not line.startswith('#')], ['base', 'archlinuxarm-keyring', 'pacman'])
        self.assertFalse((PROJECT / 'package').exists())


@unittest.skipUnless(shutil.which('sh') and shutil.which('cmp'), 'sh and cmp are required')
class EtcOverrides(unittest.TestCase):
    def test_the_hook_watches_every_override(self):
        hook = HOOK.read_text()
        targets = set(re.findall(r'^Target = (.+)$', hook, re.M))
        self.assertLessEqual(set(OVERRIDES) | {'etc/greetd/config.toml', 'etc/skel/.bashrc'}, targets)
        self.assertIn('usr/share/omarchy/etc-overrides/*', targets)
        self.assertIn('When = PostTransaction', hook)
        self.assertIn('Exec = /usr/share/libalpm/scripts/omarchy-a-etc-overrides', hook)

    def test_overrides_replace_links_and_differing_files_and_leave_the_rest(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            overrides, root = base / 'overrides', base / 'root'
            (overrides / 'etc/skel').mkdir(parents=True)
            (overrides / 'etc/os-release').write_text('NAME="Omarchy"\n')
            (overrides / 'etc/skel/.bashrc').write_text('ours\n')
            (root / 'usr/lib').mkdir(parents=True)
            (root / 'etc/skel').mkdir(parents=True)
            (root / 'usr/lib/os-release').write_text('NAME="Arch Linux ARM"\n')
            (root / 'etc/os-release').symlink_to('../usr/lib/os-release')
            (root / 'etc/skel/.bashrc').write_text('ours\n')
            os.utime(root / 'etc/skel/.bashrc', (1, 1))
            result = subprocess.run(['sh', str(OVERRIDE_SCRIPT)], capture_output=True, text=True, check=True,
                                    env={**os.environ, 'OMARCHY_ETC_OVERRIDES': str(overrides),
                                         'OMARCHY_ETC_OVERRIDES_ROOT': str(root)})
            self.assertFalse((root / 'etc/os-release').is_symlink())
            self.assertEqual((root / 'etc/os-release').read_text(), 'NAME="Omarchy"\n')
            # Never written through the link into the other package's file.
            self.assertEqual((root / 'usr/lib/os-release').read_text(), 'NAME="Arch Linux ARM"\n')
            self.assertEqual((root / 'etc/skel/.bashrc').stat().st_mtime, 1)
            self.assertEqual(result.stdout, 'omarchy-a: /etc/os-release\n')


@unittest.skipUnless(shutil.which('bash'), 'bash is required')
class Install(unittest.TestCase):
    def test_first_install_clears_only_what_an_image_before_the_package_left(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = root / 'usr/local'
            (local / 'bin').mkdir(parents=True)
            (local / 'libexec').mkdir()
            (local / 'bin/omarchy-system').symlink_to('/home/tablet/.local/share/omarchy-ipad/bin/omarchy-system')
            (local / 'bin/mine').symlink_to('/opt/mine')
            (local / 'bin/omarchy-auto-brightness').write_text('old')
            (local / 'libexec/arch-ipad-login-session').write_text('old')
            (local / 'libexec/arch-ipad-scale-output').write_text('old')
            (root / 'arch-ipad-ui-manifest.json').write_text('{}')
            script = INSTALL.read_text().replace('/usr/local', str(local)).replace(
                '/arch-ipad-ui-manifest.json', str(root / 'arch-ipad-ui-manifest.json'))
            path = root / 'package-install'
            path.write_text(script)
            subprocess.run(['bash', str(path), 'post-install', '1-1'], check=True)
            self.assertEqual(sorted(p.name for p in (local / 'bin').iterdir()), ['mine'])
            self.assertFalse((local / 'libexec').exists())
            self.assertFalse((root / 'arch-ipad-ui-manifest.json').exists())


class Audit(unittest.TestCase):
    ENTRIES = {
        'usr/share/omarchy/bin/omarchy-update': {'type': 'file', 'mode': 0o755, 'uid': 0, 'gid': 0,
                                                 'sha256': hashlib.sha256(b'update').hexdigest()},
        'usr/bin/omarchy-update': {'type': 'link', 'mode': 0o777, 'uid': 0, 'gid': 0,
                                   'link': '/usr/share/omarchy/bin/omarchy-update'},
        'usr/share/omarchy': {'type': 'dir', 'mode': 0o755, 'uid': 0, 'gid': 0},
        'usr/share/omarchy/etc-overrides/etc/os-release': {'type': 'file', 'mode': 0o644, 'uid': 0, 'gid': 0,
                                                           'sha256': hashlib.sha256(b'omarchy').hexdigest()},
        'usr/share/omarchy/migrations/1.sh': {'type': 'file', 'mode': 0o644, 'uid': 0, 'gid': 0,
                                              'sha256': hashlib.sha256(b'').hexdigest()},
        'etc/skel/.local/state/omarchy/migrations/1.sh': {'type': 'file', 'mode': 0o644, 'uid': 0, 'gid': 0,
                                                          'sha256': hashlib.sha256(b'').hexdigest()},
    }

    def root(self):
        hashes = {name: entry['sha256'] for name, entry in self.ENTRIES.items() if entry['type'] == 'file'}
        hashes['etc/os-release'] = hashlib.sha256(b'omarchy').hexdigest()
        hashes['home/tablet/.local/state/omarchy/migrations/1.sh'] = hashlib.sha256(b'').hexdigest()
        modes = {name: entry['mode'] for name, entry in self.ENTRIES.items()}
        owners = dict.fromkeys(self.ENTRIES, 0)
        links = {'usr/bin/omarchy-update': (True, '/usr/share/omarchy/bin/omarchy-update')}
        return hashes, links, modes, owners, {'usr/share/omarchy'}

    def test_a_root_as_pacman_installed_the_package_passes(self):
        hashes, links, modes, owners, directories = self.root()
        audit.verify_package(self.ENTRIES, hashes, links, modes, owners, directories)
        audit.verify_package_setup(self.ENTRIES, hashes)

    def test_changed_files_links_modes_and_a_missing_install_step_fail(self):
        for change in ('content', 'link', 'mode', 'owner', 'override', 'marker'):
            with self.subTest(change=change):
                hashes, links, modes, owners, directories = self.root()
                name = 'usr/share/omarchy/bin/omarchy-update'
                if change == 'content':
                    hashes[name] = 'changed'
                elif change == 'link':
                    links['usr/bin/omarchy-update'] = (True, '/home/tablet/.local/share/omarchy-ipad/bin/x')
                elif change == 'mode':
                    modes[name] = 0o644
                elif change == 'owner':
                    owners[name] = 1000
                elif change == 'override':
                    hashes['etc/os-release'] = 'arch'
                else:
                    del hashes['home/tablet/.local/state/omarchy/migrations/1.sh']
                with self.assertRaises(ValueError):
                    audit.verify_package(self.ENTRIES, hashes, links, modes, owners, directories)
                    audit.verify_package_setup(self.ENTRIES, hashes)

    def test_the_compiled_helpers_are_of_the_roots_architecture(self):
        self.assertEqual(set(audit.HELPERS), {'usr/libexec/omarchy-wtype',
                                              'usr/share/omarchy/trials/wvkbd-mobintl-v0.20-font18-special15-state'})
        from release.architecture import check_elf
        check_elf(elf('aarch64'), 'aarch64')
        with self.assertRaises(ValueError):
            check_elf(elf('aarch64'), 'armv7h')

    def test_the_package_mtree_is_read_whole(self):
        mtree = ('#mtree\n/set type=file uid=0 gid=0 mode=644\n'
                 './.PKGINFO time=1 size=10 sha256digest=' + 'a' * 64 + '\n'
                 './usr type=dir mode=755\n'
                 './usr/bin/omarchy-update type=link mode=777 link=/usr/share/omarchy/bin/omarchy-update\n'
                 './usr/share/omarchy/bin/omarchy-update mode=755 size=6 sha256digest=' + 'b' * 64 + '\n')
        from release.package_permissions import parse_mtree
        entries = dict(parse_mtree(mtree, every=True))
        self.assertNotIn('.PKGINFO', entries)
        self.assertEqual(entries['usr']['type'], 'dir')
        self.assertEqual(entries['usr/bin/omarchy-update']['link'], '/usr/share/omarchy/bin/omarchy-update')
        self.assertEqual(entries['usr/share/omarchy/bin/omarchy-update'], {
            'uid': 0, 'gid': 0, 'mode': 0o755, 'type': 'file', 'sha256': 'b' * 64})
        # Without EVERY only privileged entries, as before.
        self.assertEqual(list(parse_mtree(mtree)), [])


if __name__ == '__main__':
    unittest.main()
