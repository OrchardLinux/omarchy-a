from collections import Counter
from pathlib import Path
import shlex
import unittest
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
# What the omarchy-a recipe (OrchardLinux/packages, packages/omarchy-a/arch) depends on and the
# bindings run; that recipe is where a new one must be added too.
RECIPE_DEPENDS = ('grim', 'foot', 'firefox', 'wlr-randr', 'jq', 'socat', 'pipewire', 'wireplumber')


class KeyboardShortcutTests(unittest.TestCase):
    def setUp(self):
        self.tree = ET.fromstring((PROJECT / 'desktop/shell/labwc-rc.xml').read_bytes())
        self.bindings = self.tree.findall('./keyboard/keybind')

    def action(self, key):
        found = [b for b in self.bindings if b.get('key') == key]
        self.assertEqual(len(found), 1, key)
        return found[0].find('action')

    def test_every_key_is_bound_once(self):
        counts = Counter(b.get('key') for b in self.bindings)
        self.assertEqual([key for key, n in counts.items() if n > 1], [])

    def test_executed_programs_ship_with_the_image(self):
        packages = set(RECIPE_DEPENDS)
        scripts = {p.name for p in (PROJECT / 'desktop/shell/bin').iterdir()}
        for binding in self.bindings:
            action = binding.find('action')
            if action.get('name') != 'Execute':
                continue
            program = shlex.split(action.get('command'))[0]
            if program == 'sh':
                # sh -c 'setup && program …': the program is the last command.
                program = shlex.split(shlex.split(action.get('command'))[2].split('&&')[-1])[0]
            if program.startswith('/'):
                continue
            self.assertTrue(program in packages or program in scripts, (binding.get('key'), program))

    def test_omarchy_style_shortcuts(self):
        self.assertEqual(self.action('W-Return').get('command'), 'uwsm-app -- foot')
        self.assertEqual(self.action('W-S-b').get('command'), 'uwsm-app -- firefox')
        self.assertEqual(self.action('W-S-t').get('command'), 'omarchy-launch-or-focus omactivity')
        self.assertEqual(self.action('W-space').get('command'), 'omarchy-shell omarchy.dock apps')
        self.assertIn('"menu":"root"', self.action('W-A-space').get('command'))
        self.assertIn('"menu":"system"', self.action('W-Escape').get('command'))
        self.assertEqual(self.action('W-w').get('name'), 'Close')
        for key, direction in (('Up', 'up'), ('Down', 'down'), ('Left', 'left'), ('Right', 'right')):
            self.assertEqual(self.action('W-S-' + key).get('direction'), direction)
            self.assertTrue(self.action('W-' + key).get('name').endswith('WindowImmediate'))

    def test_overview_triggers(self):
        # Super+Tab, four fingers and Home pressed twice open the same overview.
        self.assertEqual(self.action('W-Tab').get('name'), 'ToggleOverview')
        overview = self.tree.find('./overview')
        self.assertEqual(overview.get('swipe'), 'yes')
        scripts = {p.name for p in (PROJECT / 'desktop/shell/bin').iterdir()}
        for attribute in ('openCommand', 'closeCommand'):
            self.assertIn(shlex.split(overview.get(attribute))[0], scripts)
        # It opens with no window too (an empty overview), not the app drawer.
        self.assertIsNone(overview.get('emptyCommand'))
        # Putting the drawer away must not toggle: it runs without knowing its state.
        shell = (PROJECT / 'desktop/shell/shell/shell.qml').read_text()
        self.assertIn('function closeApps()', shell)
        changed = (PROJECT / 'desktop/shell/bin/omarchy-overview-changed').read_text()
        self.assertIn('omarchy.dock closeApps', changed)
        self.assertIn('omarchy-keyboard hide', changed)
        self.assertIn('mode == "hide"', (PROJECT / 'desktop/shell/bin/omarchy-keyboard').read_text())
        home = (PROJECT / 'desktop/shell/bin/omarchy-home-button').read_text()
        self.assertIn('labwc --overview', home)
        # One press waits for a second before the drawer opens: two presses
        # must not flash the drawer on the way to the overview.
        self.assertLess(home.index('sleep'), home.index('omarchy-shell omarchy.dock apps'))
        # A locked session's Home is the lock screen's. (A press that woke the
        # screen or was half of Home + Power never starts the script: see
        # omarchy-powerd's 'home-up'.)
        self.assertLess(home.index('lock status'), home.index('omarchy-overview-open'))
        self.assertIn('omarchy-overview-open"', changed)
        self.assertIn('omarchy-overview-open', (PROJECT / 'desktop/shell/default/labwc/autostart').read_text())

    def test_super_tap_release_bindings_are_unchanged(self):
        for key in ('Super_L', 'Super_R'):
            binding = [b for b in self.bindings if b.get('key') == key][0]
            self.assertEqual(binding.get('onRelease'), 'yes')

class TitleTap(unittest.TestCase):
    def test_windows_keep_normal_size_and_title_taps_share_a_target(self):
        import xml.etree.ElementTree as ET
        tree=ET.parse(PROJECT/'desktop/shell/labwc-rc.xml')
        self.assertFalse(tree.findall('./windowRules/windowRule/action[@name="Maximize"]'))



@unittest.skipUnless(__import__('shutil').which('node'), 'node is required for the shortcuts page')
class ShortcutsPageTests(unittest.TestCase):
    # Settings > Keyboard > Keyboard Shortcuts names each binding; a binding
    # added to labwc-rc.xml needs a name there (ShortcutsModel.js) and a text.
    def test_every_shipped_binding_has_a_name_and_a_text(self):
        import json, subprocess
        script = r'''
const fs = require('fs');
const S = require(process.argv[1] + '/desktop/shell/shell/settings/ShortcutsModel.js');
const texts = JSON.parse(fs.readFileSync(process.argv[1] + '/desktop/shell/default/i18n/en/shell.json', 'utf8'));
const groups = S.groups(fs.readFileSync(process.argv[1] + '/desktop/shell/labwc-rc.xml', 'utf8'));
const unnamed = [], untexted = [];
for (const g of groups) for (const r of g.rows) {
  if (!r.label) unnamed.push(r.keys.join(' / ') + ': ' + r.command);
  else if (!texts[r.label]) untexted.push(r.label);
  if (!texts['shortcuts.group.' + g.group]) untexted.push('shortcuts.group.' + g.group);
}
console.log(JSON.stringify({ unnamed, untexted, groups: groups.length }));
'''
        result = subprocess.run(['node', '-e', script, str(PROJECT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        found = json.loads(result.stdout)
        self.assertEqual(found['unnamed'], [])
        self.assertEqual(found['untexted'], [])
        self.assertGreater(found['groups'], 3)

    def test_keys_read_as_on_a_keyboard(self):
        import subprocess
        script = r'''
const S = require(process.argv[1] + '/desktop/shell/shell/settings/ShortcutsModel.js');
const assert = require('assert');
assert.equal(S.keyLabel('W-S-b'), 'Super Shift B');
assert.equal(S.keyLabel('W-C-1'), 'Super Ctrl 1');
assert.equal(S.keyLabel('XF86AudioMute'), 'Mute');
// Commented-out bindings are not bindings; a swallowed key is not listed.
const g = S.groups('<!-- <keybind key="W-x"><action name="Close"/></keybind> --><keybind key="XF86HomePage"><action name="Execute" command="/usr/bin/true"/></keybind><keybind key="W-w"><action name="Close"/></keybind>');
assert.deepEqual(g.map(x => x.rows.map(r => r.keys[0])), [['Super W']]);
'''
        result = subprocess.run(['node', '-e', script, str(PROJECT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
