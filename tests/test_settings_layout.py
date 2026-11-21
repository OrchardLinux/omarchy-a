"""Settings places every menu entry, and its rows read the menu as the menu does."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'desktop/shell'


@unittest.skipUnless(shutil.which('node'), 'node is required for the Settings model')
class SettingsLayoutTests(unittest.TestCase):
    def run_node(self, body):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const root = process.argv[1];
const MM = require(root + '/shell/plugins/menu/MenuModel.js');
const L = require(root + '/shell/settings/SettingsLayout.js');
const M = require(root + '/shell/settings/SettingsModel.js');
const menu = MM.mergeMenuSources(MM.parseMenuJsonc(fs.readFileSync(root + '/default/omarchy/omarchy-menu.jsonc', 'utf8')), [], 'Go');
const ctx = (extra) => Object.assign({ items: menu.items, itemOrder: menu.itemOrder, whenResults: {}, checkedResults: {}, disabledResults: {}, values: {}, missing: {} }, extra || {});
''' + body
        result = subprocess.run(['node', '-e', script, str(ROOT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_menu_entry_has_a_place(self):
        # An upstream update that adds a menu entry fails here until the entry
        # is given a place in Settings, or named as living elsewhere.
        self.run_node(r'''
assert.deepEqual(M.unplaced(L.SECTIONS, L.ELSEWHERE, menu.items, menu.itemOrder), []);
for (const s of L.SECTIONS) for (const g of s.groups) for (const r of g.rows)
  for (const id of [].concat(r.entry || [], r.toggle || [])) assert.ok(menu.items[id], s.id + ' places ' + id + ', which the menu does not have');
''')

    def test_a_pair_is_one_switch_that_runs_the_shown_entry(self):
        self.run_node(r'''
const spec = { toggle: ['trigger.toggle.maximize-windows-on', 'trigger.toggle.maximize-windows-off'], label: 'x' };
// Maximized: only "Off" is shown, so the switch is on and runs "Off".
let row = M.resolveRow(spec, ctx({ whenResults: { 'trigger.toggle.maximize-windows-on': false, 'trigger.toggle.maximize-windows-off': true } }), {});
assert.equal(row.kind, 'switch');
assert.equal(row.on, true);
assert.equal(row.entry.id, 'trigger.toggle.maximize-windows-off');
row = M.resolveRow(spec, ctx({ whenResults: { 'trigger.toggle.maximize-windows-on': true, 'trigger.toggle.maximize-windows-off': false } }), {});
assert.equal(row.on, false);
assert.equal(row.entry.id, 'trigger.toggle.maximize-windows-on');
// Neither shown: the switch does not apply here.
assert.equal(M.resolveRow(spec, ctx({ whenResults: { 'trigger.toggle.maximize-windows-on': false, 'trigger.toggle.maximize-windows-off': false } }), {}), null);
// A submenu's X On / X Off children become one switch too.
const specs = M.menuSpecs(ctx(), 'appearance.top-bar.indicators');
assert.deepEqual(specs[0], { toggle: ['appearance.top-bar.indicators.battery-percentage-on', 'appearance.top-bar.indicators.battery-percentage-off'] });
''')

    def test_a_page_whose_rows_are_all_hidden_is_dimmed(self):
        # Touchpad Haptics on anything but a Dell XPS: every level's guard says no.
        self.run_node(r'''
const id = 'trigger.hardware.touchpad-haptics';
const kids = menu.itemOrder.filter(k => menu.items[k].parent === id);
assert.ok(kids.length > 0);
const hidden = {}; for (const k of kids) hidden[k] = false;
assert.equal(M.resolveRow({ entry: id }, ctx({ whenResults: hidden }), {}).available, false);
// Unanswered yet, or with one level shown, it opens.
assert.equal(M.resolveRow({ entry: id }, ctx(), {}).available, true);
hidden[kids[0]] = true;
assert.equal(M.resolveRow({ entry: id }, ctx({ whenResults: hidden }), {}).available, true);
''')

    def test_a_row_whose_command_is_missing_is_dimmed_and_tagged(self):
        self.run_node(r'''
const gaps = { toggle: ['appearance.windows.gaps-on', 'appearance.windows.gaps-off'] };
const commands = M.commandsIn(menu.items['appearance.windows.gaps-on'].action);
const missing = {}; for (const c of commands) missing[c] = true;
const row = M.resolveRow(gaps, ctx({ missing }), {});
assert.equal(row.available, commands.length === 0);
// A choice shows its current option as its value.
const corners = M.resolveRow({ entry: 'appearance.windows.corners' }, ctx({ checkedResults: { 'appearance.windows.corners.sharp': true } }), {});
assert.equal(corners.kind, 'choice');
assert.equal(corners.value, menu.items['appearance.windows.corners.sharp'].label);
assert.deepEqual(M.commandsIn('a=$(omarchy-foo x); omarchy-bar-set "$a" | grep omarchy'), ['omarchy-bar-set', 'omarchy-foo']);
''')

    def test_deep_links_and_state(self):
        self.run_node(r'''
// Every native page has a link of its own: Date & Time, Keyboard Shortcuts.
assert.deepEqual(M.route('datetime', L.SECTIONS, ctx()), { section: 'general', page: { kind: 'native', page: 'datetime', titleKey: 'settings.dateTime' } });
assert.deepEqual(M.route('keyboard/shortcuts', L.SECTIONS, ctx()).page.page, 'shortcuts');
assert.deepEqual(M.route('appearance/theme', L.SECTIONS, ctx()), { section: 'appearance', page: { kind: 'native', page: 'theme' } });
assert.deepEqual(M.route('setup.security', L.SECTIONS, ctx()), { section: 'security', page: { kind: 'menu', id: 'setup.security' } });
assert.deepEqual(M.route('nowhere', L.SECTIONS, ctx()), { section: '', page: null });
assert.deepEqual(M.parseState('m\tomarchy-bar\nh\tomarchy-x\nv\tappearance.icons\tPapercraft\n'), { missing: { 'omarchy-bar': true }, hyprland: { 'omarchy-x': true }, values: { 'appearance.icons': 'Papercraft' } });
// A command that is here but Hyprland's: dimmed and tagged outside Hyprland.
const corners = M.resolveRow({ entry: 'appearance.windows.corners' }, ctx({ hyprland: Object.fromEntries(M.commandsIn(menu.items['appearance.windows.corners.sharp'].action).map(c => [c, true])) }), {});
assert.equal(corners.available, false);
assert.equal(corners.tag, 'Hyprland');
const found = M.search('wallpaper', L.SECTIONS, ctx(), {}, k => k);
assert.equal(found[0].key, 'appearance.background');
assert.equal(found[0].section, 'appearance');
''')


if __name__ == '__main__':
    unittest.main()
