"""desktop/configuration/mute-switch: the output's mute follows the side switch, with no hardware access."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('mute_switch', str(PROJECT / 'desktop/configuration/mute-switch'))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

KEY_VOLUMEDOWN, KEY_VOLUMEUP, KEY_POWER, KEY_HOMEPAGE = 114, 115, 116, 172


def capabilities(codes, width=64):
    """A sysfs capabilities/key bitmap as the kernel prints it: hex longs, most significant first."""
    bits = sum(1 << code for code in codes)
    words = []
    while bits:
        words.append(bits & (1 << width) - 1)
        bits >>= width
    return ' '.join(f'{word:x}' for word in reversed(words or [0])) + '\n'


def event(kind, code, value):
    return m.EVENT.pack(0, 0, kind, code, value)


def key(value):
    return event(m.EV_KEY, m.KEY_MUTE, value)


SYN = event(m.EV_SYN, 0, 0)


class Detection(unittest.TestCase):
    def test_the_bitmap_is_read_in_the_kernels_word_width(self):
        codes = (m.KEY_MUTE, KEY_VOLUMEDOWN, KEY_VOLUMEUP, KEY_POWER, KEY_HOMEPAGE)
        for width in (32, 64):
            with self.subTest(width=width):
                text = capabilities(codes, width)
                self.assertTrue(m.has_key(text, m.KEY_MUTE, width))
                self.assertFalse(m.has_key(text, 112, width))
                self.assertFalse(m.has_key(capabilities((KEY_VOLUMEUP, KEY_POWER), width), m.KEY_MUTE, width))
        self.assertFalse(m.has_key('0\n', m.KEY_MUTE, 64))

    def test_only_gpio_keys_with_key_mute_is_a_switch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def device(name, label, codes):
                (root / name / 'device/capabilities').mkdir(parents=True)
                (root / name / 'device/name').write_text(label + '\n')
                (root / name / 'device/capabilities/key').write_text(capabilities(codes))
            device('event0', 'gpio-keys', (m.KEY_MUTE, KEY_VOLUMEDOWN, KEY_VOLUMEUP, KEY_POWER))
            device('event1', 'Apple Inc. Magic Keyboard', (m.KEY_MUTE, KEY_VOLUMEUP))  # a key, not a switch
            device('event2', 'gpio-keys', (KEY_POWER, KEY_HOMEPAGE))  # an iPad without the switch
            device('event10', 'gpio-keys', (m.KEY_MUTE,))
            (root / 'event3').mkdir()  # gone while scanned
            self.assertEqual(m.find_switches(root, 64), ['/dev/input/event0', '/dev/input/event10'])
            self.assertEqual(m.find_switches(root / 'none', 64), [])
            self.assertEqual(m.find_keys(root, 64), ['/dev/input/event1'])

    def test_the_switch_state_ioctl(self):
        self.assertEqual(m.EVIOCGKEY, 0x80604518)  # EVIOCGKEY(96): KEY_CNT bits
        self.assertEqual(m.EVENT.size, struct.calcsize('l') * 2 + 8)


class Following(unittest.TestCase):
    def test_the_start_is_read_at_once_and_set_quietly(self):
        follower = m.Follower()
        self.assertEqual(follower.wait(100.0), 0.0)
        self.assertEqual(follower.decide(True), (True, True))
        follower.done(True)
        self.assertIsNone(follower.wait(100.0))
        follower = m.Follower()
        self.assertEqual(follower.decide(False), (False, True))

    def test_a_move_is_read_back_after_it_settles_and_shown(self):
        follower = m.Follower(settle=0.3)
        follower.decide(False), follower.done(False)
        follower.feed(key(1) + SYN, 10.0)
        self.assertAlmostEqual(follower.wait(10.1), 0.2)
        self.assertEqual(follower.decide(True), (True, False))  # not quiet: the OSD
        follower.done(True)
        follower.feed(key(0) + SYN, 20.0)
        self.assertEqual(follower.decide(False), (False, False))

    def test_repeats_and_other_keys_are_no_change(self):
        follower = m.Follower()
        follower.decide(True), follower.done(True)
        follower.feed((key(2) + SYN) * 20 + event(m.EV_KEY, KEY_VOLUMEUP, 1) + SYN, 10.0)
        self.assertIsNone(follower.wait(10.0))

    def test_a_suspend_and_resume_on_silent_neither_unmutes_nor_shows(self):
        # The input core releases the held key at suspend, gpio-keys presses it at resume.
        follower = m.Follower(settle=0.3)
        follower.decide(True), follower.done(True)
        follower.feed(key(0) + SYN, 50.0)
        follower.feed(key(1) + SYN, 50.001)
        self.assertGreater(follower.wait(50.1), 0)  # nothing yet: the release is not acted on
        self.assertIsNone(follower.decide(True))   # the switch, read back: still silent

    def test_a_bouncing_contact_waits_for_the_last_change(self):
        follower = m.Follower(settle=0.3)
        follower.decide(False), follower.done(False)
        for at, value in ((10.0, 1), (10.1, 0), (10.2, 1)):
            follower.feed(key(value), at)
        self.assertAlmostEqual(follower.wait(10.4), 0.1)

    def test_dropped_events_read_the_switch_again(self):
        follower = m.Follower()
        follower.decide(False), follower.done(False)
        follower.feed(event(m.EV_SYN, m.SYN_DROPPED, 0), 10.0)
        self.assertIsNotNone(follower.wait(10.0))

    def test_a_failure_is_tried_again(self):
        follower = m.Follower(retry=2.0)
        self.assertEqual(follower.decide(True), (True, True))
        follower.failed(5.0)
        self.assertEqual(follower.wait(5.0), 2.0)
        self.assertEqual(follower.decide(True), (True, True))  # still quiet: nothing was set yet

    def test_a_partial_read_is_ignored(self):
        follower = m.Follower()
        follower.decide(False), follower.done(False)
        follower.feed(key(1)[:-3], 10.0)
        self.assertIsNone(follower.wait(10.0))


class Setting(unittest.TestCase):
    def run_with(self, results, muted, quiet):
        calls = []

        def run(argv, **_):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, results.pop(0))
        with patch.object(m.subprocess, 'run', side_effect=run):
            return m.set_mute(muted, quiet), calls

    def test_quiet_is_wpctl_and_a_move_is_omarchy_volume(self):
        self.assertEqual(self.run_with([0], True, True),
                         (True, [['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', '1']]))
        self.assertEqual(self.run_with([0], False, False), (True, [['omarchy-volume', 'mute-off']]))

    def test_without_the_osd_the_mute_is_still_set(self):
        ok, calls = self.run_with([1, 0], True, False)
        self.assertTrue(ok)
        self.assertEqual(calls, [['omarchy-volume', 'mute-on'], ['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', '1']])
        self.assertFalse(self.run_with([1, 1], True, False)[0])


class KeyboardMute(unittest.TestCase):
    """A keyboard's Mute key on a device with the switch: labwc leaves it alone, the helper toggles."""

    def test_each_press_counts_and_repeats_and_releases_do_not(self):
        self.assertEqual(m.presses(key(1) + SYN + key(2) + key(2) + key(0) + SYN), 1)
        self.assertEqual(m.presses(key(1) + key(0) + key(1) + key(0)), 2)
        self.assertEqual(m.presses(event(m.EV_KEY, KEY_VOLUMEUP, 1) + SYN), 0)
        self.assertEqual(m.presses(key(1)[:10]), 0)  # a partial read

    def toggle_with(self, results):
        calls = []

        def run(argv, **_):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, results.pop(0))
        with patch.object(m.subprocess, 'run', side_effect=run):
            return m.toggle_mute(), calls

    def test_a_press_toggles_with_the_osd(self):
        self.assertEqual(self.toggle_with([0]), (True, [['omarchy-volume', 'mute-toggle']]))

    def test_without_the_osd_it_still_toggles(self):
        self.assertEqual(self.toggle_with([1, 0]),
                         (True, [['omarchy-volume', 'mute-toggle'], ['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', 'toggle']]))


class Session(unittest.TestCase):
    def test_without_a_switch_it_exits_and_leaves_no_flag(self):
        with tempfile.TemporaryDirectory() as runtime, \
                patch.dict(os.environ, {'XDG_RUNTIME_DIR': runtime, 'LABWC_PID': ''}), \
                patch.object(m, 'find_switches', return_value=[]), \
                patch.object(m.signal, 'signal'), patch.object(m, 'log'):
            self.assertEqual(m.main(), 0)
            self.assertEqual(os.listdir(runtime), [])

    def test_the_flag_names_this_process_and_goes_with_it(self):
        with tempfile.TemporaryDirectory() as runtime, patch.dict(os.environ, {'XDG_RUNTIME_DIR': runtime}):
            m.raise_flag()
            flag = Path(runtime) / 'omarchy-mute-switch'
            self.assertEqual(flag.read_text(), f'{os.getpid()}\n')
            m.lower_flag()
            self.assertFalse(flag.exists())
            flag.write_text('1\n')  # another's: left alone
            m.lower_flag()
            self.assertTrue(flag.exists())

    def test_the_package_stages_it_and_the_session_starts_it(self):
        install = (PROJECT / 'desktop/install-tree').read_text()
        self.assertIn('$config/mute-switch usr/libexec/omarchy-mute-switch 755', install)
        autostart = (PROJECT / 'desktop/shell/default/labwc/autostart').read_text()
        self.assertIn('/usr/libexec/omarchy-mute-switch > "$XDG_RUNTIME_DIR/omarchy-mute-switch.log" 2>&1 &',
                      autostart)
        rc = (PROJECT / 'desktop/shell/labwc-rc.xml').read_text()
        block = rc[rc.index('<keybind key="XF86AudioMute" allowWhenLocked="yes">'):]
        self.assertIn('command="omarchy-volume mute-key"', block[:block.index('</keybind>')])
        self.assertNotIn('mute-toggle', rc)


MIGRATION = PROJECT / 'desktop/shell/migrations/1795508927.sh'


@unittest.skipUnless(shutil.which('bash'), 'bash is required')
class Migration(unittest.TestCase):
    def migrate(self, text):
        with tempfile.TemporaryDirectory() as home:
            rc = Path(home) / '.config/labwc/rc.xml'
            if text is not None:
                rc.parent.mkdir(parents=True)
                rc.write_text(text)
            result = subprocess.run(['bash', '-euo', 'pipefail', str(MIGRATION)], capture_output=True, text=True,
                                    env={'PATH': os.environ['PATH'], 'HOME': home}, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return rc.read_text() if rc.exists() else None

    def test_the_shipped_binding_becomes_mute_key(self):
        shipped = (PROJECT / 'desktop/shell/labwc-rc.xml').read_text()
        old = shipped.replace('omarchy-volume mute-key', 'omarchy-volume mute-toggle')
        self.assertNotEqual(old, shipped)
        migrated = self.migrate(old)
        self.assertIn('<action name="Execute" command="omarchy-volume mute-key" />', migrated)
        self.assertNotIn('mute-toggle', migrated)
        self.assertEqual(migrated, old.replace('mute-toggle', 'mute-key'))
        self.assertEqual(self.migrate(migrated), migrated)

    def test_a_users_own_bindings_are_left_alone(self):
        own = ('<keyboard>\n'
               '    <keybind key="W-m">\n'
               '      <action name="Execute" command="omarchy-volume mute-toggle" />\n'
               '    </keybind>\n'
               '    <keybind key="XF86AudioMute" allowWhenLocked="yes">\n'
               '      <action name="Execute" command="pactl set-sink-mute @DEFAULT_SINK@ toggle" />\n'
               '    </keybind>\n'
               '</keyboard>\n')
        self.assertEqual(self.migrate(own), own)
        self.assertIsNone(self.migrate(None))


if __name__ == '__main__':
    unittest.main()
