"""A finger is no mouse: Qt Quick's frame-synchronous hover is off in the session and the apps it starts."""
from pathlib import Path
import re
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SESSION = PROJECT / 'desktop/configuration/login-session'


class TouchHover(unittest.TestCase):
    def test_qt_quick_does_not_hover_under_a_finger(self):
        text = SESSION.read_text()
        # Exported before labwc starts, for the shell and everything labwc runs.
        export = text.index('export QT_QUICK_FRAME_SYNCHRONOUS_HOVER_INTERVAL=-1')
        self.assertLess(export, text.index('labwc -m'))
        # And in the user manager, for apps started as their own units (uwsm-app).
        imported = re.search(r'systemctl --user import-environment [^\n]*QT_QUICK_FRAME_SYNCHRONOUS_HOVER_INTERVAL', text)
        self.assertIsNotNone(imported)
        self.assertLess(export, imported.start())


if __name__ == '__main__':
    unittest.main()
