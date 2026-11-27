"""The image takes the platform's packages from the Orchard package repository, and its own files as
the omarchy-a package built from the same checkout (release/package.py).

system/assemble-rootfs with a pacman that records its calls: no network, no root.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
ASSEMBLE = PROJECT / 'system/assemble-rootfs'
PACMAN_CONF = '''[options]
#Architecture = auto
Architecture = aarch64
SigLevel = Required DatabaseOptional

[core]
Include = /etc/pacman.d/mirrorlist

[extra]
Include = /etc/pacman.d/mirrorlist

[alarm]
Include = /etc/pacman.d/mirrorlist
'''
ORCHARD = {'aarch64': ['wlroots0.20', 'labwc', 'omafox', 'omactivity', 'folio-touch', 'mesa', 'libva-v4l2-request'],
           'armv7h': ['wlroots0.20', 'labwc', 'omafox', 'omactivity', 'folio-touch', 'omacalc']}


def section(start, end):
    text = ASSEMBLE.read_text()
    return text[text.index(start):text.index(end)]


def bash(script, **env):
    return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + script], text=True, capture_output=True, timeout=30,
                          env={'PATH': os.environ['PATH'], **env})


@unittest.skipUnless(shutil.which('bash') and shutil.which('awk'), 'bash and awk are required')
class Repositories(unittest.TestCase):
    """pacman.conf of the build and of the image: [orchard] > [omarchy] (64-bit) > Arch Linux ARM."""
    def configure(self, architecture, source=PACMAN_CONF):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / 'pacman.conf'
            conf.write_text(source)
            result = bash(section('orchard_siglevel=', 'build_pacman=$(mktemp -d)') + 'repositories "$CONF" "$CONF"\n',
                          CONF=str(conf), architecture=architecture)
            return result.returncode, conf.read_text()

    def test_order_on_64_bit(self):
        code, text = self.configure('aarch64')
        self.assertEqual(code, 0)
        self.assertEqual(re.findall(r'^\[([\w-]+)\]$', text, re.M),
                         ['options', 'orchard', 'omarchy', 'core', 'extra', 'alarm'])
        self.assertIn('[orchard]\nSigLevel = Optional TrustAll\n'
                      'Server = https://github.com/OrchardLinux/packages/releases/download/repo-$arch\n\n'
                      '[omarchy]\nServer = https://pkgs.omarchy.org/stable/$arch\n\n[core]\n', text)
        # Everything else is as it was.
        self.assertEqual(text.replace(text[text.index('[orchard]'):text.index('[core]')], ''), PACMAN_CONF)

    def test_armv7_has_orchard_and_no_omarchy(self):
        code, text = self.configure('armv7h')
        self.assertEqual(code, 0)
        self.assertEqual(re.findall(r'^\[([\w-]+)\]$', text, re.M), ['options', 'orchard', 'core', 'extra', 'alarm'])

    def test_a_file_that_already_lists_one_is_refused(self):
        for name in ('orchard', 'omarchy'):
            source = PACMAN_CONF.replace('[core]', f'[{name}]\nServer = x\n\n[core]')
            self.assertEqual(self.configure('aarch64', source), (1, source))
        self.assertEqual(self.configure('aarch64', PACMAN_CONF.replace('[core]', '[main]'))[0], 1)

    def test_unsigned_for_now_and_the_place_that_changes_is_marked(self):
        text = ASSEMBLE.read_text()
        self.assertIn("orchard_siglevel='Optional TrustAll'", text)
        self.assertIn('# SIGNING:', text)
        self.assertIn('SigLevel = Required DatabaseOptional', text)


@unittest.skipUnless(shutil.which('bash'), 'bash is required')
class Installation(unittest.TestCase):
    def install(self, architecture, planned=None, consistent=True, owner='mesa', ours='omarchy-a-build', built=()):
        """The package installation with a pacman that records its calls.

        PLANNED: what pacman says the transaction takes from [orchard]; OURS: the repository omarchy-a comes from;
        BUILT: the Orchard packages built from a packages checkout, which pacman takes from OURS.
        """
        planned = ORCHARD[architecture] if planned is None else planned
        block = section('for name in "${orchard_packages[@]}"; do\n  [[ " ${requested[*]} "', 'useradd --root')
        block = block.replace('"$project/system/pacman-download"', 'pacman download').replace(
            'repositories "$root/etc/pacman.conf" "$root/etc/pacman.conf"', 'echo repositories >> "$LOG"')
        packages = section('mapfile -t orchard_packages', '# Install signed packages into a clean target')
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'calls'
            script = ('pacman() { echo "$*" >> "$LOG"; case " $* " in\n'
                      '  *" --print "*) printf "core/base\\n$OURS/omarchy-a\\n"; for name in $PLANNED; do\n'
                      '    if [[ " $BUILT " == *" $name "* ]]; then echo "$OURS/$name"; else echo "orchard/$name"; fi; done;;\n'
                      '  *" -Qoq "*) echo "$OWNER"; echo "$OWNER";;\n'
                      '  *" -Dk "*) [[ -n $CONSISTENT ]];; esac; }\n'
                      'config=c root=/r gpgdir=g desktop=/d requested=(base labwc) local_names=($BUILT)\n'
                      + packages + block)
            result = bash(script, LOG=str(log), architecture=architecture, PLANNED=' '.join(planned), OWNER=owner,
                          CONSISTENT='1' if consistent else '', OURS=ours, BUILT=' '.join(built), project=str(PROJECT))
            calls = [re.sub(r'^(download )?(--(config|root|gpgdir) \S+ )+', r'\1', line)
                     for line in log.read_text().splitlines()]
            return result.returncode, calls, result.stderr

    def test_one_transaction_installs_ours_with_everything_else(self):
        code, calls, error = self.install('aarch64')
        self.assertEqual(code, 0, error)
        # labwc is asked for once.
        wanted = 'base labwc wlroots0.20 omafox omactivity folio-touch mesa libva-v4l2-request omarchy-a'
        self.assertEqual(calls[:3], [f'download -Sy --noconfirm {wanted}',
                                     f'-S --print --print-format %r/%n {wanted}', f'-S --noconfirm {wanted}'])
        self.assertEqual(calls[3], 'repositories')
        self.assertEqual(calls[4], '-Dk')
        self.assertIn('/r/usr/lib/libvulkan_powervr_mesa.so /r/usr/lib/orchard/gpu-probe', calls[5])
        self.assertEqual(len(calls), 6)
        # Arch's mesa never arrives, so nothing is removed; and no package is a local file.
        self.assertFalse([call for call in calls if re.search(r'(^| )-(R|U)', call)])
        self.assertNotIn('-U', ASSEMBLE.read_text())

    def test_armv7_takes_files_and_omacalc_from_ours_and_keeps_archs_mesa(self):
        code, calls, error = self.install('armv7h')
        self.assertEqual(code, 0, error)
        wanted = 'base labwc wlroots0.20 omafox omactivity folio-touch omacalc omarchy-a'
        self.assertEqual(calls, [f'download -Sy --noconfirm {wanted}', f'-S --print --print-format %r/%n {wanted}',
                                 f'-S --noconfirm {wanted}', 'repositories', '-Dk'])

    def test_a_package_of_ours_taken_elsewhere_stops_before_anything_installs(self):
        for planned in ([name for name in ORCHARD['aarch64'] if name != 'mesa'],  # mesa would be Arch's
                        ORCHARD['aarch64'] + ['firefox'], []):
            with self.subTest(planned=planned):
                code, calls, error = self.install('aarch64', planned=planned)
                self.assertNotEqual(code, 0)
                self.assertIn('Expected from [orchard] exactly', error)
                self.assertEqual(len(calls), 2)

    def test_packages_built_from_a_packages_checkout_come_from_the_build_repository(self):
        code, calls, error = self.install('aarch64', built=('labwc', 'wlroots0.20'))
        self.assertEqual(code, 0, error)
        self.assertEqual(calls[3:5], ['repositories', '-Dk'])
        # Built here but taken from [orchard] anyway (another repository listed first) is refused.
        code, calls, error = self.install('aarch64', ours='orchard', built=('labwc',))
        self.assertNotEqual(code, 0)
        self.assertIn('Expected from [orchard] exactly', error)

    def test_the_build_lists_the_checkouts_packages_with_omarchy_a(self):
        text = ASSEMBLE.read_text()
        self.assertIn('cp "$file" "$build_pacman/omarchy-a-build/"', text)
        self.assertIn('repo-add -q "$build_pacman/omarchy-a-build/omarchy-a-build.db.tar.gz" '
                      '"$build_pacman/omarchy-a-build/"*.pkg.tar.zst', text)

    def test_the_package_list_is_per_architecture(self):
        for architecture, names in ORCHARD.items():
            result = bash(section('mapfile -t orchard_packages', '# Install signed packages into a clean target')
                          + 'echo "${orchard_packages[*]}"', architecture=architecture, project=str(PROJECT))
            self.assertEqual(result.stdout.split(), names, result.stderr)

    def test_omarchy_a_from_anywhere_but_this_checkout_is_refused(self):
        # [orchard]'s omarchy-a is the last release, not this checkout; nor is anyone else's.
        for ours in ('orchard', 'omarchy'):
            code, calls, error = self.install('aarch64', ours=ours)
            self.assertNotEqual(code, 0)
            self.assertEqual(len(calls), 2)
        self.assertIn('Expected omarchy-a built from this checkout', error)

    def test_the_build_installs_the_package_of_this_checkout_and_the_image_lists_the_published_one(self):
        text = ASSEMBLE.read_text()
        self.assertIn('repo-add -q "$build_pacman/omarchy-a-build/omarchy-a-build.db.tar.gz"', text)
        # Listed before [orchard] in the build's pacman.conf only; the image's never names it.
        self.assertIn('$0 == "[orchard]" && !done { print "[omarchy-a-build]"', text)
        self.assertLess(text.index('repositories /etc/pacman.conf "$config"'), text.index('[omarchy-a-build]'))
        self.assertIn('repositories "$root/etc/pacman.conf" "$root/etc/pacman.conf"', text)
        # The tablet user's home is made from /etc/skel after the package filled it, never copied.
        self.assertLess(text.index('pacman --config "$config" --root "$root" --gpgdir "$gpgdir" -S --noconfirm'),
                        text.index('useradd --root'))
        self.assertNotIn('payload', text)

    def test_an_unmet_dependency_or_another_mesa_is_refused(self):
        self.assertNotEqual(self.install('aarch64', consistent=False)[0], 0)
        self.assertNotEqual(self.install('armv7h', consistent=False)[0], 0)
        self.assertNotEqual(self.install('aarch64', owner='mesa-aurora')[0], 0)

    def test_files_is_the_file_manager_of_every_board(self):
        # Dolphin is on no image: not asked for, no launcher entry or wrapper staged.
        self.assertNotIn('dolphin', (PROJECT / 'system/packages.txt').read_text().split())
        self.assertNotIn('dolphin', ASSEMBLE.read_text().lower())
        self.assertNotIn('dolphin', (PROJECT / 'desktop/install-tree').read_text().lower())
        self.assertFalse((PROJECT / 'desktop/shell/bin/omarchy-dolphin').exists())

    def test_the_login_finds_the_probe_the_mesa_package_ships(self):
        # The package has it at /usr/lib/orchard/gpu-probe and links it from where the login looks.
        self.assertIn('gpu_probe=/usr/lib/omarchy-a/gpu-probe',
                      (PROJECT / 'desktop/configuration/login-session').read_text())


if __name__ == '__main__':
    unittest.main()
