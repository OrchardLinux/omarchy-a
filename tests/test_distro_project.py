"""This checkout as an orchard distribution: distro.toml and its build entry. No builds."""
import importlib.util
from pathlib import Path
import unittest

from orchard import distro

PROJECT = Path(__file__).resolve().parents[1]


class DistributionProject(unittest.TestCase):
    def test_distro_toml_names_this_distribution_and_its_entry(self):
        settings = distro.settings(PROJECT)
        self.assertEqual(settings['name'], 'omarchy-a')
        self.assertEqual(settings['build'], PROJECT / 'tools/build.py')

    def test_every_component_input_exists(self):
        spec = importlib.util.spec_from_file_location('omarchy_build', PROJECT / 'tools/build.py')
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        for name, inputs in entry.INPUTS.items():
            for path in inputs:
                with self.subTest(component=name, path=path):
                    self.assertTrue((PROJECT / path).exists())


if __name__ == '__main__':
    unittest.main()
