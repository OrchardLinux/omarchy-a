from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'desktop/shell/bin/omarchy-keyboard'

TAP = 'release 80 2'
DRAG = 'release 600 140'
LONG_PRESS = 'release 900 3'


def load():
    loader = SourceFileLoader('omarchy_keyboard', str(SCRIPT))
    module = module_from_spec(spec_from_loader('omarchy_keyboard', loader))
    loader.exec_module(module)
    return module


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class KeyboardPolicyTests(unittest.TestCase):
    """When the on-screen keyboard opens and closes on its own (omarchy-keyboard listen)."""

    def setUp(self):
        self.clock = Clock()
        self.shown = False
        self.calls = []

        def show():
            self.shown = True
            self.calls.append('show')

        def hide():
            self.shown = False
            self.calls.append('hide')

        self.policy = load().Policy(show, hide, lambda: self.shown, now=self.clock)

    def facts(self, *lines):
        for line in lines:
            self.policy.fact(line)

    def wait(self, seconds):
        self.clock.t += seconds
        self.policy.tick()

    # Programs moving focus

    def test_an_app_focusing_its_field_on_start_does_not_open_it(self):
        self.facts('field on 2', 'show')           # omactivity's search, Qt asking by itself
        self.wait(1)
        self.assertEqual(self.calls, [])

    def test_a_version_1_app_focusing_a_field_by_itself_does_not_open_it(self):
        self.facts('field on 1')                   # Firefox's address bar on start
        self.wait(1)
        self.assertEqual(self.calls, [])

    def test_a_panel_focusing_its_search_after_a_tap_elsewhere_does_not(self):
        self.facts('press', TAP, 'field on 2')     # the Apps row; the drawer focuses its search, asking nothing
        self.wait(1)
        self.assertEqual(self.calls, [])

    # Taps on fields

    def test_an_app_asking_during_a_touch_opens_it(self):
        self.facts('field on 2', 'press', 'show')  # Qt on a press on a field that has focus
        self.assertEqual(self.calls, ['show'])

    def test_an_app_asking_right_after_a_tap_opens_it(self):
        self.facts('field on 2', 'press', TAP, 'show')
        self.assertEqual(self.calls, ['show'])

    def test_a_request_before_its_field_is_kept_a_moment(self):
        self.facts('press', TAP, 'show', 'field on 2')  # Folio: the path label becomes a field
        self.assertEqual(self.calls, ['show'])

    def test_a_request_long_before_its_field_is_not(self):
        self.facts('press', TAP, 'show')
        self.wait(1)
        self.facts('field on 2')
        self.assertEqual(self.calls, [])

    def test_a_tap_in_a_version_1_field_opens_it(self):
        self.facts('field on 1', 'press', TAP)      # a terminal, or a field that kept focus
        self.assertEqual(self.calls, ['show'])

    def test_a_tap_that_focuses_a_version_1_field_opens_it(self):
        self.facts('press', 'field on 1', TAP)
        self.assertEqual(self.calls, ['show'])

    def test_a_version_1_field_coming_on_right_after_a_tap_opens_it(self):
        self.facts('press', TAP, 'field on 1')
        self.assertEqual(self.calls, ['show'])

    def test_a_tap_that_moves_focus_off_a_version_1_field_does_not(self):
        self.facts('field on 1', 'press', 'field off', TAP)
        self.wait(1)
        self.assertEqual(self.calls, [])

    def test_selecting_text_by_dragging_does_not_open_it(self):
        self.facts('field on 1', 'press', DRAG)
        self.wait(1)
        self.assertEqual(self.calls, [])

    def test_a_long_press_does_not_open_it(self):
        self.facts('field on 1', 'press', LONG_PRESS)
        self.wait(1)
        self.assertEqual(self.calls, [])

    def test_a_drag_does_not_let_a_late_field_open_it(self):
        self.facts('press', DRAG, 'field on 1', 'show')
        self.assertEqual(self.calls, [])

    # Closing

    def test_leaving_the_field_closes_it_shortly_after(self):
        self.facts('field on 2', 'press', 'show', 'field off')
        self.assertEqual(self.calls, ['show'])
        self.wait(0.3)
        self.assertEqual(self.calls, ['show', 'hide'])

    def test_moving_to_the_next_field_keeps_it_open(self):
        self.facts('field on 2', 'press', 'show', 'field off', 'field on 2')
        self.wait(1)
        self.assertEqual(self.calls, ['show'])

    def test_the_app_can_close_it(self):
        self.facts('field on 2', 'press', 'show', 'hide')
        self.wait(0.3)
        self.assertEqual(self.calls, ['show', 'hide'])

    def test_a_tap_after_the_person_put_it_away_opens_it_again(self):
        # Qt is not told of the swipe; the field asks hide-then-show to be heard.
        self.facts('field on 2', 'press', 'show')
        self.policy.person('hide')
        self.shown = False  # the swipe put it away
        self.calls.clear()
        self.wait(1)
        self.facts('press', 'hide', 'show')
        self.wait(1)
        self.assertEqual(self.calls, ['show'])

    def test_tapping_the_same_field_again_after_it_closed_on_its_own_opens_it(self):
        # Qt with the focus fix: tapping outside turns the field off; Qt still
        # thinks the keyboard is up and asks nothing on the next tap.
        self.facts('press', 'field on 2', TAP, 'show')
        self.facts('press', 'field off', TAP)
        self.wait(1)
        self.facts('press', 'field on 2', TAP)
        self.wait(1)
        self.assertEqual(self.calls, ['show', 'hide', 'show'])

    def test_a_field_focused_after_the_finger_lifts_does_not_open_it(self):
        self.facts('press', TAP, 'field on 2')     # a click handler focusing a field
        self.wait(1)
        self.assertEqual(self.calls, [])

    def test_hide_then_show_at_once_does_not_blink_an_open_keyboard(self):
        self.facts('field on 2', 'press', 'show')
        self.facts('press', 'hide', 'show')
        self.wait(1)
        self.assertEqual(self.calls, ['show'])  # still up, not shown twice

    def test_one_the_person_opened_stays_when_the_field_goes(self):
        self.facts('field on 2')
        self.policy.person('show')
        self.facts('field off')
        self.wait(1)
        self.facts('hide')
        self.assertEqual(self.calls, [])

    def test_one_the_person_put_away_stays_away_until_the_next_tap(self):
        self.facts('field on 2', 'press', 'show')
        self.policy.person('hide')
        self.shown = False  # the swipe put it away
        self.wait(1)
        self.facts('show', 'field off', 'field on 2')
        self.wait(1)
        self.assertEqual(self.calls, ['show'])
        self.facts('press', 'show')
        self.assertEqual(self.calls, ['show', 'show'])

    # A physical keyboard

    def test_typing_on_a_physical_keyboard_closes_it_and_taps_stop_opening_it(self):
        self.facts('keyboards 1', 'field on 2', 'press', 'show', 'key')
        self.assertEqual(self.calls, ['show', 'hide'])
        self.facts('press', 'show', 'field on 1', 'press', TAP)
        self.wait(1)
        self.assertEqual(self.calls, ['show', 'hide'])

    def test_a_connected_keyboard_alone_changes_nothing(self):
        self.facts('keyboards 1', 'field on 2', 'press', 'show')
        self.assertEqual(self.calls, ['show'])

    def test_opening_it_by_hand_ends_physical_typing(self):
        self.facts('keyboards 1', 'field on 2', 'key')
        self.policy.person('show')
        self.facts('press', 'show')
        self.assertEqual(self.calls, ['show'])
        self.assertFalse(self.policy.hardware)

    def test_no_physical_keyboard_left_ends_physical_typing(self):
        self.facts('keyboards 1', 'field on 2', 'key', 'keyboards 0', 'press', 'show')
        self.assertEqual(self.calls, ['show'])

    def test_keys_without_a_physical_keyboard_change_nothing(self):
        self.facts('keyboards 0', 'field on 2', 'press', 'show', 'key')
        self.assertEqual(self.calls, ['show'])

    def test_a_bad_line_is_ignored(self):
        self.facts('field on x', 'keyboards', 'release 5', 'release a b', 'nonsense', '')
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
