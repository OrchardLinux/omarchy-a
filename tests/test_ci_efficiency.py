"""The release workflow builds beside the tests and keeps what need not be made again; no GitHub calls."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def job(text, name):
    match = re.search(r'^  ' + re.escape(name) + r':\n(.*?)(?=^  [\w-]+:\n|\Z)', text, re.M | re.S)
    if match is None:
        raise AssertionError('Missing job: ' + name)
    return match.group(1)


class CIEfficiency(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/build.yml').read_text()

    def test_builds_start_beside_the_tests_and_only_assembly_waits_for_them(self):
        for name in ('artwork-check', 'artwork', 'userspace'):
            needs = re.search(r'^    needs: (.*)$', job(self.workflow, name), re.M)
            self.assertNotIn('test', needs.group(1) if needs else '', name)
        self.assertIn('needs: [test, orchard, artwork, userspace]', job(self.workflow, 'assets'))
        # The draft release goes through the assembly.
        self.assertIn('needs: assets', job(self.workflow, 'draft'))

    def test_artwork_needs_a_mac_only_when_boot_changed(self):
        key = "key: boot-artwork-v1-${{ hashFiles('boot/**') }}"
        check, artwork = job(self.workflow, 'artwork-check'), job(self.workflow, 'artwork')
        self.assertIn('runs-on: ubuntu-24.04', check)
        self.assertIn('lookup-only: true', check)
        self.assertIn(key, check)
        self.assertIn(key, artwork)
        self.assertIn('runs-on: ${{ needs.artwork-check.outputs.runner }}', artwork)
        self.assertEqual(artwork.count("steps.kept.outputs.cache-hit != 'true'"), 3)

    def test_no_package_but_omarchy_a_is_built_here(self):
        # Mesa, wlroots, Labwc and the rest come built from the Orchard package repository.
        body = job(self.workflow, 'userspace')
        for gone in ('ccache', 'makepkg', 'build-sources', 'build-labwc', 'labwc/install-toolchain', 'useradd',
                     'desktop/build '):
            self.assertNotIn(gone, body)
        # The one package: this commit's omarchy-a, with the package repository's recipe; nothing publishes it.
        self.assertIn('python -m release.package --output out/package --architecture aarch64', body)
        self.assertIn('fetch-depth: 0', body)
        self.assertIn('system/build-rootfs --package out/package', body)
        for gone in ('publish-package', 'package-armv7h', 'package-aarch64', 'repo-add'):
            self.assertNotIn(gone, self.workflow)
        self.assertFalse((ROOT / 'ci/publish-package').exists())
        self.assertFalse((ROOT / 'package').exists())
        for gone in ('desktop/build-sources', 'desktop/build-labwc', 'desktop/packages', 'desktop/labwc'):
            self.assertFalse((ROOT / gone).exists(), gone)
        # What is compiled is the keyboard and the cursor helper: the toolchain is a C compiler, no more.
        toolchain = (ROOT / 'desktop/install-toolchain').read_text()
        for gone in ('meson', 'llvm', 'clang', 'base-devel', 'mesa'):
            self.assertNotRegex(toolchain, r'(?m)^packages=.*\b' + gone + r'\b')
        self.assertNotIn('labwc', self.workflow.replace('Labwc', ''))

    def test_the_root_archive_is_not_compressed_twice_on_its_way_to_assembly(self):
        self.assertIn('tar -C out -cf out/omarchy-userspace.tar base', job(self.workflow, 'userspace'))
        self.assertIn('tar -xf out/downloads/omarchy-userspace.tar* -C out', job(self.workflow, 'assets'))


if __name__ == '__main__':
    unittest.main()
