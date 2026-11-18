"""With a packages checkout (orchard build --packages), the image's [orchard] packages that it has
other recipes of are built from it (tools/build.py), once per recipe, in the order they need each other."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('omarchy_a_build', PROJECT / 'tools/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class LocalPackages(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.project = self.root / 'omarchy-a'
        (self.project / 'system').mkdir(parents=True)
        shutil.copy(PROJECT / 'system/orchard-packages.txt', self.project / 'system')
        self.checkout = self.root / 'packages'
        for name in build.PACKAGES_BUILD:
            (self.checkout / name).parent.mkdir(parents=True, exist_ok=True)
            (self.checkout / name).write_text(name)
        self.builds = []

    def plan(self, rows):
        return json.dumps({'arch': 'aarch64', 'packages': [
            {'name': name, 'version': '1:1-1', 'recipe': recipe, 'published': '1:1-1', 'build': changed,
             'needs': needs} for name, recipe, changed, needs in rows]})

    def fake_build(self, argv, cwd, check, env):
        _, _, name, arch, version = argv
        self.builds.append((name, sorted(os.listdir(env['LOCAL_REPO']))))
        (Path(env['OUT']) / f'{name}-1.1-1-{arch}.pkg.tar.zst').write_text(name)
        return subprocess.CompletedProcess(argv, 0)

    def run_build(self, rows):
        with patch.object(build, 'PROJECT', self.project), \
                patch.object(build.subprocess, 'check_output', return_value=self.plan(rows)) as asked, \
                patch.object(build.subprocess, 'run', self.fake_build), patch('builtins.print'):
            built = build.local_packages(self.checkout, 'aarch64')
        return built, asked.call_args.args[0]

    def test_the_images_list_is_asked_for_and_only_other_recipes_are_built_after_what_they_need(self):
        rows = [('mesa', 'm', False, []), ('wlroots0.20', 'w', True, ['mesa']), ('labwc', 'l', True, ['wlroots0.20'])]
        built, asked = self.run_build(rows)
        self.assertEqual(asked[2:], ['local', '--arch', 'aarch64', 'wlroots0.20', 'labwc', 'omafox', 'omactivity',
                                     'folio-touch', 'qt6-base', 'mesa', 'libva-v4l2-request'])
        self.assertEqual(list(built), ['wlroots0.20', 'labwc'])
        # labwc builds against the wlroots just built, which its build takes ahead of [orchard]'s.
        self.assertEqual(self.builds, [('wlroots0.20', []), ('labwc', ['wlroots0.20-1.1-1-aarch64.pkg.tar.zst'])])
        self.assertTrue(built['labwc'][0].is_file())

    def test_an_unchanged_recipe_is_built_once_and_what_it_was_built_against_counts(self):
        rows = [('wlroots0.20', 'w', True, []), ('labwc', 'l', True, ['wlroots0.20'])]
        first, _ = self.run_build(rows)
        again, _ = self.run_build(rows)
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(first, again)
        # Another wlroots recipe: both again, labwc against the new wlroots.
        changed, _ = self.run_build([('wlroots0.20', 'w2', True, []), ('labwc', 'l', True, ['wlroots0.20'])])
        self.assertEqual([name for name, _ in self.builds[2:]], ['wlroots0.20', 'labwc'])
        self.assertNotEqual(changed['labwc'][1], first['labwc'][1])

    def test_nothing_is_built_when_every_recipe_is_published(self):
        built, _ = self.run_build([('labwc', 'l', False, [])])
        self.assertEqual((built, self.builds), ({}, []))


if __name__ == '__main__':
    unittest.main()
