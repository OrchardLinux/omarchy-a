"""The image takes the platform's packages from the Orchard package repository; nothing is built here.

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
ORCHARD = {'aarch64': ['wlroots0.20', 'labwc', 'omafox', 'mesa', 'libva-v4l2-request'],
           'armv7h': ['wlroots0.20', 'labwc', 'omafox', 'omacalc']}


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
        self.assertEqual(re.findall(r'^\[(\w+)\]$', text, re.M), ['options', 'orchard', 'omarchy', 'core', 'extra', 'alarm'])
        self.assertIn('[orchard]\nSigLevel = Optional TrustAll\n'
                      'Server = https://github.com/OrchardLinux/packages/releases/download/repo-$arch\n\n'
                      '[omarchy]\nServer = https://pkgs.omarchy.org/stable/$arch\n\n[core]\n', text)
        # Everything else is as it was.
        self.assertEqual(text.replace(text[text.index('[orchard]'):text.index('[core]')], ''), PACMAN_CONF)

    def test_armv7_has_orchard_and_no_omarchy(self):
        code, text = self.configure('armv7h')
        self.assertEqual(code, 0)
        self.assertEqual(re.findall(r'^\[(\w+)\]$', text, re.M), ['options', 'orchard', 'core', 'extra', 'alarm'])

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
    def install(self, architecture, planned=None, consistent=True, owner='mesa'):
        """The package installation with a pacman that records its calls.

        PLANNED: what pacman says the transaction takes from [orchard].
        """
        planned = ORCHARD[architecture] if planned is None else planned
        block = section('for name in "${orchard_packages[@]}"; do\n  [[ " ${requested[*]} "', 'useradd --root')
        block = block.replace('"$project/system/pacman-download"', 'pacman download').replace(
            'repositories "$root/etc/pacman.conf" "$root/etc/pacman.conf"', 'echo repositories >> "$LOG"')
        packages = section('orchard_packages=(wlroots0.20', 'for package in "${local_packages[@]}"')
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'calls'
            script = ('pacman() { echo "$*" >> "$LOG"; case " $* " in\n'
                      '  *" --print "*) printf "core/base\\n"; for name in $PLANNED; do echo "orchard/$name"; done;;\n'
                      '  *" -Qoq "*) echo "$OWNER"; echo "$OWNER";;\n'
                      '  *" -Dk "*) [[ -n $CONSISTENT ]];; esac; }\n'
                      'config=c root=/r gpgdir=g desktop=/d requested=(base labwc dolphin)\n' + packages + block)
            result = bash(script, LOG=str(log), architecture=architecture, PLANNED=' '.join(planned), OWNER=owner,
                          CONSISTENT='1' if consistent else '')
            calls = [re.sub(r'^(download )?(--(config|root|gpgdir) \S+ )+', r'\1', line)
                     for line in log.read_text().splitlines()]
            return result.returncode, calls, result.stderr

    def test_one_transaction_installs_ours_with_everything_else(self):
        code, calls, error = self.install('aarch64')
        self.assertEqual(code, 0, error)
        # Files takes Dolphin's place on 64-bit; labwc is asked for once.
        wanted = 'base labwc wlroots0.20 omafox mesa libva-v4l2-request'
        self.assertEqual(calls[:3], [f'download -Sy --noconfirm {wanted}',
                                     f'-S --print --print-format %r/%n {wanted}', f'-S --noconfirm {wanted}'])
        self.assertEqual(calls[3], 'repositories')
        # Only the two packages the repository does not have yet are local files.
        self.assertEqual(calls[4], '--noconfirm -U /d/packages/omactivity.pkg.tar.zst /d/packages/folio.pkg.tar.zst')
        self.assertEqual(calls[5], '-Dk')
        self.assertIn('/r/usr/lib/libvulkan_powervr_mesa.so /r/usr/lib/orchard/gpu-probe', calls[6])
        self.assertEqual(len(calls), 7)
        # Arch's mesa never arrives: nothing is removed.
        self.assertFalse([call for call in calls if re.search(r'(^| )-R', call)])

    def test_armv7_takes_omacalc_from_ours_and_keeps_archs_mesa_and_dolphin(self):
        code, calls, error = self.install('armv7h')
        self.assertEqual(code, 0, error)
        wanted = 'base labwc dolphin wlroots0.20 omafox omacalc'
        self.assertEqual(calls, [f'download -Sy --noconfirm {wanted}', f'-S --print --print-format %r/%n {wanted}',
                                 f'-S --noconfirm {wanted}', 'repositories', '-Dk'])

    def test_a_package_of_ours_taken_elsewhere_stops_before_anything_installs(self):
        for planned in (['wlroots0.20', 'labwc', 'omafox', 'libva-v4l2-request'],  # mesa would be Arch's
                        ORCHARD['aarch64'] + ['firefox'], []):
            with self.subTest(planned=planned):
                code, calls, error = self.install('aarch64', planned=planned)
                self.assertNotEqual(code, 0)
                self.assertIn('Expected from [orchard] exactly', error)
                self.assertEqual(len(calls), 2)

    def test_an_unmet_dependency_or_another_mesa_is_refused(self):
        self.assertNotEqual(self.install('aarch64', consistent=False)[0], 0)
        self.assertNotEqual(self.install('armv7h', consistent=False)[0], 0)
        self.assertNotEqual(self.install('aarch64', owner='mesa-aurora')[0], 0)

    def test_the_login_finds_the_probe_the_mesa_package_ships(self):
        # The package has it at /usr/lib/orchard/gpu-probe and links it from where the login looks.
        self.assertIn('gpu_probe=/usr/lib/omarchy-a/gpu-probe',
                      (PROJECT / 'desktop/configuration/login-session').read_text())


if __name__ == '__main__':
    unittest.main()
