"""Discovery ordering only: retain anonymous peers, after named devices."""
from pathlib import Path
import shutil
import subprocess
import unittest


class BluetoothDiscoverySortTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is required for Bluetooth model validation')
    def test_named_discoveries_precede_anonymous_without_changing_other_sections(self):
        model = Path(__file__).resolve().parents[1] / 'desktop/shell/shell/plugins/panels/bluetooth/Model.js'
        script = r'''
const assert = require('node:assert/strict');
const model = require(process.argv[1]);
const peers = [
  {address: '00:00:00:00:00:02', name: '00-00-00-00-00-02'},
  {address: '00:00:00:00:00:04', name: 'Zebra headphones'},
  {address: '00:00:00:00:00:01'},
  {address: '00:00:00:00:00:03', name: '00:00:00:00:00:03', deviceName: 'Alpha keyboard'},
  {address: '00:00:00:00:00:05', name: '0000180f-0000-1000-8000-00805f9b34fb'},
];
const original = peers.slice();
const discovered = model.deviceLists(peers).discovered;
assert.deepEqual(discovered.map(d => d.address), [
  '00:00:00:00:00:03', '00:00:00:00:00:04',
  '00:00:00:00:00:01', '00:00:00:00:00:02', '00:00:00:00:00:05',
]);
assert.deepEqual(peers, original); // Sorting must not mutate the backend list.
assert.equal(discovered.length, peers.length); // Unnamed peers remain actionable.
assert.deepEqual(model.deviceLists([]).discovered, []);
assert.deepEqual(model.deviceLists(peers.filter(d => model.hasHumanName(d))).discovered.map(d => d.deviceName || d.name),
                 ['Alpha keyboard', 'Zebra headphones']);
assert.deepEqual(model.deviceLists(peers.filter(d => !model.hasHumanName(d))).discovered.map(d => d.address),
                 ['00:00:00:00:00:01', '00:00:00:00:00:02', '00:00:00:00:00:05']);
const sections = model.deviceLists([
  {address: '00:00:00:00:00:01', name: 'Zebra', connected: true},
  {address: '00:00:00:00:00:02', name: 'Alpha', connected: true},
  {address: '00:00:00:00:00:03', name: 'Zebra', paired: true},
  {address: '00:00:00:00:00:04', name: 'Alpha', trusted: true},
]);
assert.deepEqual(sections.connected.map(d => d.name), ['Alpha', 'Zebra']);
assert.deepEqual(sections.known.map(d => d.name), ['Alpha', 'Zebra']);
assert.equal(sections.discovered.length, 0);
'''
        result = subprocess.run(['node', '-e', script, str(model)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
