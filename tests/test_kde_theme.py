import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'desktop/shell/bin/omarchy-theme-set-kde'
loader = importlib.machinery.SourceFileLoader('kde_theme', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
kde = importlib.util.module_from_spec(spec)
loader.exec_module(kde)


class KDEThemeTests(unittest.TestCase):
    def test_preserves_other_settings_and_reapplies_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'palette'
            dest = root / 'kdeglobals'
            source.write_text('[Colors:View]\nBackgroundNormal=1,2,3\n[Colors:Window]\nBackgroundNormal=4,5,6\n')
            dest.write_text('# preferences\n[General]\nTerminalApplication=foot\n[Colors:View]\nBackgroundNormal=9,9,9\nCustomKey=hello\n[Icons]\nTheme=my-icons\n')
            kde.publish(source, dest)
            first = dest.read_text()
            for expected in ('# preferences', 'TerminalApplication=foot', 'CustomKey=hello', 'Theme=my-icons', 'BackgroundNormal=1,2,3', '[Colors:Window]'):
                self.assertIn(expected, first)
            self.assertNotIn('BackgroundNormal=9,9,9', first)
            kde.publish(source, dest)
            self.assertEqual(first, dest.read_text())

    def test_invalid_palette_does_not_change_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, dest = root / 'palette', root / 'kdeglobals'
            source.write_text('[Colors:View]\nBackgroundNormal={{ background_rgb }}\n')
            dest.write_text('original\n')
            with self.assertRaises(ValueError):
                kde.publish(source, dest)
            self.assertEqual(dest.read_text(), 'original\n')

    def test_dolphin_launcher_uses_kde_plugin_only_for_dolphin(self):
        desktop = (ROOT / 'desktop/configuration/org.kde.dolphin.desktop').read_text()
        wrapper = (ROOT / 'desktop/shell/bin/omarchy-dolphin').read_text()
        self.assertIn('Exec=omarchy-dolphin %U', desktop)
        self.assertIn('DBusActivatable=false', desktop)
        self.assertIn('QT_QPA_PLATFORMTHEME=kde', wrapper)
        self.assertIn('exec /usr/bin/dolphin', wrapper)


if __name__ == '__main__':
    unittest.main()
