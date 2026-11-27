"""The lock screen's PIN layout: a tall phone gets a larger, lower keypad while the clock keeps its place."""
from pathlib import Path
import re
import unittest

VIEW = Path(__file__).resolve().parents[1] / 'desktop/shell/shell/plugins/lock/LockView.qml'

# Logical sizes, portrait: iPhone XR (and the other notched iPhones), iPhone 8, iPod touch 6.
XR, IPHONE8, IPOD = (414, 896), (375, 667), (320, 568)


def metrics():
    """The three metric sets in source order: tall phone, phone, tablet (portrait values)."""
    text = VIEW.read_text()
    block = text[text.index('readonly property var metrics:'):]
    block = block[:block.index('function pt(')]
    sets = []
    for literal in re.findall(r'\{([^{}]*)\}', block):
        values = {}
        for key, value in re.findall(r'(\w+):\s*([^,]+?)(?=,\s*\w+:|\s*$)', literal.strip()):
            # "landscape ? a : b": the portrait value.
            values[key] = float(value.split(':')[-1]) if '?' in value else float(value)
        sets.append(values)
    return sets


def tall_phone(width, height):
    phone = min(width, height) < 600
    return phone and width <= height and height >= 2 * width


def placement(m, height):
    """Top of the clock and of the keys on a portrait screen; the clock's own height cancels out."""
    keys = 4 * m['keyHeight'] + 3 * m['keyGap']
    group = m['between'] + m['slotRow'] + m['stack'] + keys
    top = 24 + m['lower']
    bottom = 16  # a phone's bottom margin
    clock = top + (height - top - bottom - group) / 2
    return clock, clock + m['between'] + m['slotRow'] + m['stack']


class LockLayout(unittest.TestCase):
    def test_the_rule_in_the_view_is_the_one_tested_here(self):
        self.assertIn('readonly property bool tallPhone: phone && !landscape && height >= 2 * width', VIEW.read_text())
        self.assertIn('anchors.topMargin: Style.space(24) + root.pt("lower")', VIEW.read_text())

    def test_only_tall_phones_held_upright_get_the_tall_layout(self):
        self.assertTrue(tall_phone(*XR))
        self.assertFalse(tall_phone(*IPHONE8))
        self.assertFalse(tall_phone(*IPOD))
        self.assertFalse(tall_phone(896, 414))
        self.assertFalse(tall_phone(768, 1024))

    def test_on_a_tall_phone_the_clock_stays_and_the_keys_come_lower_and_larger(self):
        tall, phone, _ = metrics()
        clock_tall, keys_tall = placement(tall, XR[1])
        clock_phone, keys_phone = placement(phone, XR[1])
        self.assertEqual(clock_tall, clock_phone)
        self.assertEqual(keys_tall - keys_phone, 52)
        self.assertGreater(tall['keyWidth'], phone['keyWidth'])
        self.assertGreater(tall['keyHeight'], phone['keyHeight'])
        self.assertGreater(tall['stack'], phone['stack'])

    def test_the_tall_keypad_fits_the_screen_with_its_margins(self):
        tall, _, _ = metrics()
        width = 3 * tall['keyWidth'] + 2 * tall['keyColumnGap']
        self.assertLessEqual(width, XR[0] - 2 * 16)
        _, keys = placement(tall, XR[1])
        self.assertLessEqual(keys + 4 * tall['keyHeight'] + 3 * tall['keyGap'], XR[1] - 16)

    def test_shorter_phones_and_tablets_keep_their_place(self):
        _, phone, tablet = metrics()
        self.assertEqual(phone['lower'], 0)
        self.assertEqual(tablet['lower'], 0)


if __name__ == '__main__':
    unittest.main()
