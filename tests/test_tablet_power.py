import importlib.machinery
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import call, patch

PATH = Path(__file__).resolve().parents[1] / 'desktop/shell/bin/omarchy-tablet-power'
loader = importlib.machinery.SourceFileLoader('tablet_power', str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
power = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/tmp'}):
    loader.exec_module(power)


class TabletPowerTests(unittest.TestCase):
    def test_blanks_before_requesting_or_checking_lock(self):
        events = []
        states = iter([{'secure': False}, {'secure': False}, {'secure': True}])
        def status():
            events.append('status')
            return next(states)
        with patch.object(power, 'status', side_effect=status), \
             patch.object(power, 'command', side_effect=lambda *args: events.append('lock') or 'ok'), \
             patch.object(power.time, 'sleep'), \
             patch.object(power, 'set_visible', side_effect=lambda visible: events.append(('visible', visible))):
            power.lock_and_blank()
        self.assertEqual(events, [('visible', False), 'status', 'lock', 'status', 'status'])

    def test_unconfirmed_lock_restores_display(self):
        with patch.object(power, 'status', return_value={'secure': False}), \
             patch.object(power, 'command', return_value='ok'), \
             patch.object(power.time, 'monotonic', side_effect=[0, 1, 9]), \
             patch.object(power.time, 'sleep'), patch.object(power, 'set_visible') as visible:
            with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
                power.lock_and_blank()
            self.assertEqual(visible.call_args_list, [call(False), call(True)])

    def test_rejected_lock_restores_display(self):
        with patch.object(power, 'status', return_value={'secure': False}), \
             patch.object(power, 'command', return_value='missing-pam'), \
             patch.object(power, 'set_visible') as visible:
            with self.assertRaisesRegex(RuntimeError, 'rejected'):
                power.lock_and_blank()
            self.assertEqual(visible.call_args_list, [call(False), call(True)])

    def test_restore_failure_is_reported(self):
        with patch.object(power, 'status', side_effect=RuntimeError('no shell')), \
             patch.object(power, 'set_visible', side_effect=[None, RuntimeError('no backlight')]):
            with self.assertRaisesRegex(RuntimeError, 'display restore failed'):
                power.lock_and_blank()

if __name__ == '__main__':
    unittest.main()
