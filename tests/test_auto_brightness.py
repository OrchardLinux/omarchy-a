"""Ported ALS policy and power-daemon cooperation, with no hardware access."""
import importlib.machinery
import importlib.util
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('auto_brightness', str(PROJECT/'desktop/configuration/auto-brightness'))
spec = importlib.util.spec_from_loader(loader.name, loader)
a = importlib.util.module_from_spec(spec); loader.exec_module(a)

class AutoBrightness(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.panel = self.root/'backlight/panel'; self.panel.mkdir(parents=True)
        (self.panel/'max_brightness').write_text('1000\n'); self.set_raw(500)
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME':str(self.root/'config'),
            'XDG_STATE_HOME':str(self.root/'state'), 'XDG_RUNTIME_DIR':str(self.root),
            'IPAD_ALS_BACKLIGHT_ROOT':str(self.root/'backlight')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.conf = a.load_conf()

    def set_raw(self, value): (self.panel/'brightness').write_text(str(value)+'\n')

    def test_default_off_and_persisted_switch(self):
        self.assertFalse(a.is_enabled(self.conf))
        a.set_state('auto_brightness','on'); self.assertTrue(a.is_enabled(self.conf))
        a.set_state('auto_brightness','off'); self.assertFalse(a.is_enabled(self.conf))

    def test_curve_and_median_ignore_one_spike(self):
        points = a.parse_curve(a.DEFAULT_CURVE)
        self.assertEqual(a.curve_pct(points, 80), 58)
        self.assertEqual(a.curve_pct(points, 100000), 100)
        smooth = a.Smoother(0)
        for i, lux in enumerate((20,20,20,20000,20)): smooth.feed(lux,float(i))
        self.assertAlmostEqual(smooth.lux,20)

    def test_brightening_is_fast_and_darkening_slow(self):
        # Hands-on test 2026-11-08: a flashlight took seconds to register, then moved in steps.
        up=a.Smoother(3.0,tau_up=0.4); down=a.Smoother(3.0,tau_up=0.4)
        for t in (0.0,0.25,0.5): up.feed(20,t); down.feed(2000,t)
        for t in (0.75,1.0,1.25,1.5): up.feed(2000,t); down.feed(20,t)
        self.assertGreater(up.lux,800)     # most of the way within ~1 s of a flashlight
        self.assertGreater(down.lux,300)   # a shadow does not dim at once
        policy=a.Policy(self.conf); policy.ref_level=0.0; policy.last_move=10.0
        class S: level=math.log1p(1000); lux=1000
        self.assertIsNotNone(policy.decide(S,10.3,30.0))   # brighter: 0.25 s spacing
        policy.last_move=10.0
        class D: level=math.log1p(0.5); lux=0.5
        policy.ref_level=math.log1p(1000)
        self.assertIsNone(policy.decide(D,10.3,90.0))      # darker: keeps the 2 s spacing

    def test_powerd_missing_or_dark_is_a_hold(self):
        for reply in ('','dark'):
            with patch.object(a,'power_request',return_value=reply): self.assertEqual(a.holds(),['powerd'])
        with patch.object(a,'power_request',return_value='lit'): self.assertEqual(a.holds(),[])

    def test_automatic_write_is_compare_and_set_through_powerd(self):
        panel=a.Backlight('panel')
        with patch.object(a,'power_request',return_value='ok') as request:
            self.assertTrue(panel.write(600,expected=500))
            request.assert_called_once_with('brightness panel 600 500')
        for raw in (0,501):
            self.set_raw(raw)
            with patch.object(a,'power_request') as request:
                self.assertFalse(panel.write(600,expected=500)); request.assert_not_called()

    def test_hysteresis_and_manual_override(self):
        panel=a.Backlight('panel'); self.conf['enabled']=True
        daemon=a.Daemon(self.conf,type('Source',(),{'kind':'test'})(),panel,False,False)
        daemon.last_written=500; self.set_raw(300); daemon.latest=1500
        with patch.object(a,'holds',return_value=[]), patch.object(panel,'write') as write:
            daemon.tick(10.0)
            self.assertGreater(daemon.override_until,10.0); write.assert_not_called()

    def test_ramp_is_a_smooth_perceptual_fade(self):
        panel=a.Backlight('panel'); self.conf['enabled']=True
        daemon=a.Daemon(self.conf,type('Source',(),{'kind':'test'})(),panel,False,False)
        self.set_raw(100); daemon.goal_raw=800; daemon.start_ramp(100,0.0)
        self.assertGreaterEqual(daemon.ramp_secs,a.RAMP_MIN_SECS); self.assertLessEqual(daemon.ramp_secs,a.RAMP_MAX_SECS)
        written=[]
        def fake_write(new,expected=None):
            self.assertEqual(expected,int((self.panel/'brightness').read_text())); self.set_raw(new); written.append(new); return True
        with patch.object(panel,'write',side_effect=fake_write):
            t=0.0
            while daemon.ramping() and t<10:
                daemon.step(int((self.panel/'brightness').read_text()),t); t+=a.RAMP_TICK
        self.assertEqual(written[-1],800); self.assertFalse(daemon.ramping())
        self.assertEqual(written,sorted(written))  # monotonic, no overshoot
        self.assertGreater(len(written),10)  # a fade of many small steps, not a few jumps
        p=[daemon.perceived(w) for w in [100]+written]
        steps=[b-c for c,b in zip(p,p[1:])]
        self.assertLess(max(steps),0.08)  # no single step brighter than ~8% perceived
        self.assertLess(steps[0],max(steps))  # eased in: starts gentler than the middle

    def test_public_root_and_fresh_staging_both_include_helpers(self):
        from release.public_root import desktop_additions, desktop_replacements
        additions=desktop_additions(); replacements=desktop_replacements()
        self.assertEqual(additions['usr/local/libexec/arch-ipad-auto-brightness'][1],0o755)
        for command in ('omarchy-auto-brightness',):
            self.assertIn('usr/local/bin/'+command,additions)
        self.assertIn('usr/local/libexec/arch-ipad-rotate-output',replacements)
        stage=(PROJECT/'desktop/stage.py').read_text()
        self.assertIn('arch-ipad-auto-brightness',stage)
        self.assertIn('arch-ipad-auto-brightness',(PROJECT/'desktop/configuration/labwc-autostart').read_text())

if __name__=='__main__': unittest.main()
