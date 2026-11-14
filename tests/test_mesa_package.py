"""On 64-bit boards OpenGL comes from OrchardLinux's Mesa: one package in the place of Arch's mesa."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
RECIPE = PROJECT / 'desktop/packages/mesa-orchard/PKGBUILD'
ASSEMBLE = PROJECT / 'system/assemble-rootfs'
START, END = "# wlroots0.20 replaces Arch's build", 'useradd --root'


def recipe(*names):
    """The recipe's variables as makepkg reads them: {name: [values]}."""
    script = 'source "$1"; shift; for name; do declare -n ref=$name; printf "%s\\n" "$name" "${ref[@]}" ""; done'
    out = subprocess.run(['bash', '-c', script, 'recipe', str(RECIPE), *names], text=True, capture_output=True,
                         check=True, timeout=30).stdout
    return {block[0]: block[1:] for block in (part.split('\n') for part in out.strip('\n').split('\n\n'))}


def setups():
    """The meson setup lines of the recipe by build directory: {directory: text}."""
    text = RECIPE.read_text().replace('\\\n', ' ')
    return {match[1]: match[0] for match in re.finditer(r'meson setup \S+ (build-\w+) .*', text)}


class Package(unittest.TestCase):
    def test_takes_the_place_of_archs_mesa(self):
        values = recipe('pkgname', 'pkgver', 'pkgrel', 'arch', 'provides', 'conflicts', 'depends')
        self.assertEqual((values['pkgname'], values['arch']), (['mesa-orchard'], ['aarch64']))
        version = f"1:{values['pkgver'][0]}-{values['pkgrel'][0]}"
        # What packages on the image ask Arch's mesa for: libglvnd asks for mesa and opengl-driver,
        # wlroots for opengl-driver. Arch's mesa has epoch 1 and is older than the fork.
        for name in (f'mesa={version}', f'mesa-libgl={version}', 'opengl-driver', 'vulkan-driver'):
            self.assertIn(name, values['provides'])
        self.assertTrue(values['pkgver'][0].startswith('27.'))
        # Both cannot be installed: they own the same files.
        self.assertIn('mesa', values['conflicts'])
        # llvmpipe needs the LLVM it was built with: a versioned dependency, not a silent break.
        self.assertIn('libLLVM.so', values['depends'])
        self.assertNotIn('mesa', values['depends'])

    def test_is_the_pinned_fork_commit(self):
        pin = json.loads((PROJECT / 'desktop/arm64/sources.json').read_text())['mesa']
        text = RECIPE.read_text()
        self.assertIn(f"_commit={pin['commit']}\n", text)
        self.assertIn(pin['sha256'], text)
        self.assertEqual(recipe('pkgver')['pkgver'], ['27.0.0.dev.' + pin['commit'][:11]])
        self.assertIn('OrchardLinux/mesa', pin['urls'][0])

    def test_opengl_drivers(self):
        gl = setups()['build-gl']
        # Zink for the GPU desktop; llvmpipe and softpipe for every board without one and every software fallback.
        self.assertIn('-Dgallium-drivers=zink,llvmpipe,softpipe ', gl)
        for option in ('-Dopengl=true', '-Dgles2=enabled', '-Degl=enabled', '-Dgbm=enabled', '-Dglx=dri',
                       '-Dglvnd=enabled', '-Dplatforms=x11,wayland', '-Dvulkan-drivers= ', '--buildtype=release'):
            self.assertIn(option, gl)
        text = RECIPE.read_text()
        self.assertIn('for driver in zink llvmpipe softpipe; do grep -q', text)
        # The A9's S3TC default is a line of the fork's driconf file: the package must carry it.
        self.assertIn('device="g5p"', text)
        self.assertIn('transcode_s3tc', text)

    def test_vulkan_driver_is_built_as_before(self):
        vulkan = setups()['build-vulkan']
        for option in ('--buildtype=debugoptimized', '-Dplatforms=wayland', '-Dvulkan-drivers=imagination',
                       '-Dgallium-drivers= ', '-Dopengl=false', '-Degl=disabled', '-Dgbm=disabled'):
            self.assertIn(option, vulkan)
        text = RECIPE.read_text()
        self.assertIn('build-vulkan/src/imagination/vulkan/libvulkan_powervr_mesa.so', text)
        self.assertIn('"${pkgdir}/usr/share/vulkan/icd.d/powervr_mesa_icd.json"', text)

    def test_probe_links_this_packages_gbm(self):
        self.assertRegex(RECIPE.read_text().replace('\\\n', ' '),
                         r'cc .* gpu-probe\.c -o gpu-probe .*\s-Lbuild-gl/src/gbm -lgbm ')

    def test_build_and_image_take_the_package(self):
        sources = (PROJECT / 'desktop/build-sources').read_text()
        self.assertIn('"$ORCHARD_RECIPE"/packages/mesa-orchard/{PKGBUILD,gpu-probe.c}', sources)
        for path in ('usr/lib/libvulkan_powervr_mesa.so', 'usr/lib/libEGL_mesa.so.0', 'usr/lib/libgbm.so.1',
                     'usr/lib/dri/zink_dri.so', 'usr/lib/dri/swrast_dri.so'):
            self.assertIn(path, sources)
        self.assertIn("'mesa-orchard.pkg.tar.zst': ('gpu_recipe_sha256', 'packages/mesa-orchard')",
                      (PROJECT / 'desktop/build').read_text())
        self.assertIn('"$desktop/packages/mesa-orchard.pkg.tar.zst"', ASSEMBLE.read_text())
        self.assertFalse((PROJECT / 'desktop/packages/vulkan-powervr-orchard').exists())


class Image(unittest.TestCase):
    def install(self, architecture, owner='mesa-orchard', consistent=True):
        """The local package installation of assemble-rootfs with a pacman that records its calls."""
        text = ASSEMBLE.read_text()
        block = text[text.index(START):text.index(END)]
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'calls'
            script = ('set -euo pipefail\n'
                      'pacman() { echo "$*" >> "$LOG"; case " $* " in\n'
                      '  *" -Qoq "*) echo "$OWNER"; echo "$OWNER";;\n'
                      '  *" -Dk "*) [[ -n $CONSISTENT ]];; esac; }\n'
                      'config=c root=/r gpgdir=g local_packages=(wlroots.pkg mesa-orchard.pkg)\n' + block)
            result = subprocess.run(['bash', '-c', script], text=True, capture_output=True, timeout=30,
                                    env={'PATH': os.environ['PATH'], 'LOG': str(log), 'OWNER': owner,
                                         'architecture': architecture, 'CONSISTENT': '1' if consistent else ''})
            calls = [re.sub(r'^(--(config|root|gpgdir) \S+ )+', '', line) for line in log.read_text().splitlines()]
            return result.returncode, calls

    def test_archs_mesa_leaves_before_the_fork_arrives(self):
        code, calls = self.install('aarch64')
        self.assertEqual(code, 0)
        self.assertEqual(calls[:4], ['--noconfirm -Rdd mesa', '--noconfirm -U wlroots.pkg',
                                     '--noconfirm -U mesa-orchard.pkg', '-Dk'])
        self.assertEqual(len(calls), 5)

    def test_image_with_an_unmet_dependency_or_archs_opengl_is_refused(self):
        self.assertNotEqual(self.install('aarch64', consistent=False)[0], 0)
        self.assertNotEqual(self.install('aarch64', owner='mesa')[0], 0)

    def test_armv7_keeps_archs_mesa(self):
        code, calls = self.install('armv7h')
        self.assertEqual((code, calls), (0, ['--noconfirm -U wlroots.pkg', '--noconfirm -U mesa-orchard.pkg']))


if __name__ == '__main__':
    unittest.main()
