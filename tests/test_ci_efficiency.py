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

    def test_source_builds_keep_their_compiler_cache_across_temporary_build_directories(self):
        body = job(self.workflow, 'userspace')
        self.assertIn('path: .ccache', body)
        self.assertIn('restore-keys: desktop-ccache-v1-\n', body)
        self.assertIn('CCACHE_DIR="$GITHUB_WORKSPACE/.ccache" CCACHE_BASEDIR=/tmp CCACHE_NOHASHDIR=1', body)
        # Restored before the workspace is handed to the unprivileged builder.
        self.assertLess(body.index('path: .ccache'), body.index('chown -R builder:builder "$GITHUB_WORKSPACE"'))
        # The compiler cache is CI's: the toolchain recipes local builds share do not install it.
        for recipe in ('desktop/install-toolchain', 'desktop/labwc/install-toolchain', 'system/install-toolchain'):
            self.assertNotIn('ccache', (ROOT / recipe).read_text())

    def test_the_root_archive_is_not_compressed_twice_on_its_way_to_assembly(self):
        self.assertIn('tar -C out -cf out/omarchy-userspace.tar base', job(self.workflow, 'userspace'))
        self.assertIn('tar -xf out/downloads/omarchy-userspace.tar* -C out', job(self.workflow, 'assets'))


if __name__ == '__main__':
    unittest.main()
