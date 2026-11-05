"""A snapshot may describe boards with identity only; they have no firmware to keep private."""
import json
from pathlib import Path
import tempfile
import unittest

from release import snapshot


class IdentityOnlyBoards(unittest.TestCase):
    def test_private_firmware_skips_a_board_with_no_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'devices/k93').mkdir(parents=True)
            (root / 'devices/k93/device.toml').write_text('schema = 1\n')
            (root / 'devices/j71b').mkdir()
            (root / 'devices/j71b/device.toml').write_text('[firmware]\nrecipe = "firmware.json"\n')
            (root / 'devices/j71b/firmware.json').write_text(
                json.dumps({'outputs': [{'destination': 'lib/firmware/a.bin'}]}))
            self.assertEqual(snapshot.private_firmware(root), {'lib/firmware/a.bin'})


if __name__ == '__main__':
    unittest.main()
