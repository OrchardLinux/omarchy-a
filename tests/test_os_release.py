import unittest

from release.public_root import system_files


class OsRelease(unittest.TestCase):
    def test_system_names_itself_omarchy(self):
        data, mode = system_files()['etc/os-release']
        fields = dict(line.split('=', 1) for line in data.decode().splitlines())
        self.assertEqual((fields['PRETTY_NAME'], fields['ID'], mode), ('"Omarchy"', 'omarchy', 0o644))
        self.assertIn('arch', fields['ID_LIKE'])


if __name__ == '__main__':
    unittest.main()
