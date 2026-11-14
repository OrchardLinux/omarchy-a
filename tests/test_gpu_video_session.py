"""The login session picks the GPU and the video decoder from what the board has and a probe shows to work; software stays the default."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SESSION = PROJECT / 'desktop/configuration/login-session'
START, END = '# A board with a GPU', 'export PATH=/usr/local/bin:/usr/bin'


PROBE = '/usr/lib/omarchy-a/gpu-probe'
PASS = 'echo "GPU-PROBE PASS renderer=zink"'


def detection():
    """The hardware block of the session, reading a fake /sys, running a fake probe and printing what it exported."""
    text = SESSION.read_text()
    block = text[text.index(START):text.index(END)]
    assert PROBE in block and 'tick < 100' in block
    return block.replace('/sys/', '"$FAKE"/sys/').replace(PROBE, '"$FAKE"/gpu-probe').replace(
        '-e /usr/share/vulkan/icd.d/powervr_mesa_icd.json', '-n ${ICD:-}').replace('tick < 100', 'tick < ${TICKS:-100}')


class Session(unittest.TestCase):
    def run_session(self, devices, icd=True, probe=PASS, ticks=None):
        """devices: {sysfs class path: (device path, driver name)}; probe: the probe's shell text, None for no probe."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, (device, driver) in devices.items():
                node = root / 'sys/class' / name
                node.mkdir(parents=True)
                target = root / 'sys/devices' / device
                (target / 'driver-dir' / driver).mkdir(parents=True, exist_ok=True)
                if not (target / 'driver').exists():
                    (target / 'driver').symlink_to(target / 'driver-dir' / driver)
                (node / 'device').symlink_to(target)
            if probe is not None:
                (root / 'gpu-probe').write_text('#!/bin/sh\necho "$@" > "$FAKE/probe-args"\n'
                                                'env > "$FAKE/probe-env"\n' + probe + '\n')
                (root / 'gpu-probe').chmod(0o755)
            # The journal is a file here: the session's logger call lands in it.
            script = ('set -euo pipefail\nlogger() { shift 3; echo "$*" >> "$FAKE/journal"; }\n'
                      'export WLR_RENDERER=pixman LIBGL_ALWAYS_SOFTWARE=1\n' + detection() +
                      '\nenv | grep -E "^(WLR_|MESA_|PVR_|LIBGL_|LIBVA_|MOZ_)" | sort')
            env = {'PATH': os.environ['PATH'], 'FAKE': str(root), 'XDG_RUNTIME_DIR': str(root),
                   **({'ICD': '1'} if icd else {}), **({'TICKS': str(ticks)} if ticks else {})}
            result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True, check=True,
                                    timeout=30)
            read = lambda name: (root / name).read_text() if (root / name).exists() else None
            self.journal, self.probe_args, self.probe_env = read('journal'), read('probe-args'), read('probe-env')
            return dict(line.split('=', 1) for line in result.stdout.splitlines())

    GPU = {'drm/renderD128': ('soc/gpu', 'powervr'), 'drm/card0': ('soc/gpu', 'powervr'),
           'drm/card1': ('soc/display', 'apple-adbe'), 'drm/card1-eDP-1': ('soc/display/drm/card1', 'none')}
    DECODER = {'video4linux/video0': ('soc/video-codec', 'apple-vxd')}

    SOFTWARE = {'WLR_RENDERER': 'pixman', 'LIBGL_ALWAYS_SOFTWARE': '1'}

    def test_software_desktop_without_the_hardware(self):
        self.assertEqual(self.run_session({}), self.SOFTWARE)
        # A display controller alone, or another driver's render node, is no reason to leave pixman.
        self.assertEqual(self.run_session({'drm/card0': ('soc/display', 'apple-adbe'),
                                           'drm/renderD128': ('soc/other', 'other-gpu')}), self.SOFTWARE)
        # Such a board runs no probe and gets no journal line: nothing changes for it.
        self.assertEqual((self.probe_args, self.journal), (None, None))

    def test_software_desktop_when_the_image_cannot_test_the_gpu(self):
        # The kernel driver without this image's Vulkan driver cannot draw.
        self.assertEqual(self.run_session(self.GPU, icd=False), self.SOFTWARE)
        self.assertEqual(self.probe_args, None)
        self.assertIn('software desktop: this image has no Vulkan driver', self.journal)
        # Without the probe, or without a display card, nothing vouches for the GPU.
        self.assertEqual(self.run_session(self.GPU, probe=None), self.SOFTWARE)
        self.assertIn('software desktop: no display card or no gpu-probe', self.journal)
        gpu_only = {name: device for name, device in self.GPU.items() if not name.startswith('drm/card1')}
        self.assertEqual(self.run_session(gpu_only), self.SOFTWARE)
        self.assertEqual(self.probe_args, None)

    def test_probe_runs_as_the_desktop_would(self):
        env = self.run_session(self.GPU)
        self.assertEqual(self.probe_args.split(), ['/dev/dri/renderD128', '/dev/dri/card1'])
        probe_env = dict(line.split('=', 1) for line in self.probe_env.splitlines() if '=' in line)
        for name in ('WLR_RENDERER', 'WLR_RENDER_DRM_DEVICE', 'WLR_DRM_DEVICES', 'MESA_LOADER_DRIVER_OVERRIDE',
                     'PVR_I_WANT_A_BROKEN_VULKAN_DRIVER'):
            self.assertEqual(probe_env[name], env[name])
        self.assertNotIn('LIBGL_ALWAYS_SOFTWARE', probe_env)
        self.assertRegex(self.journal, r'^GPU desktop after \d+\.\d s: GPU-PROBE PASS renderer=zink\n$')

    def test_failed_probe_keeps_the_software_desktop(self):
        # Any board: the kernel driver is there, but drawing through it does not work in this boot.
        env = self.run_session(self.GPU, probe='echo "mesa: some warning"\n'
                                               'echo "GPU-PROBE FAIL: the display controller cannot import" >&2\nexit 1')
        self.assertEqual(env, self.SOFTWARE)
        self.assertEqual(self.journal, 'software desktop: GPU-PROBE FAIL: the display controller cannot import\n')
        # A probe that dies without a word (a crash in a driver) is a failure too.
        self.assertEqual(self.run_session(self.GPU, probe='kill -SEGV $$'), self.SOFTWARE)
        self.assertEqual(self.journal, 'software desktop: the GPU probe failed\n')

    def test_probe_that_never_ends_does_not_hold_the_login(self):
        # It ignores TERM and would run for a minute; the session moves on after its wait (0.3 s here).
        env = self.run_session(self.GPU, probe="trap '' TERM\nexec sleep 60", ticks=3)
        self.assertEqual(env, self.SOFTWARE)
        self.assertEqual(self.journal, 'software desktop: the GPU probe did not finish within 10 s\n')

    def test_probe_recipe_is_the_file_next_to_it(self):
        # makepkg checks gpu-probe.c against the recipe: both must change together.
        recipe = PROJECT / 'desktop/packages/vulkan-powervr-orchard'
        self.assertIn(hashlib.sha256((recipe / 'gpu-probe.c').read_bytes()).hexdigest(),
                      (recipe / 'PKGBUILD').read_text())
        self.assertIn(f'"${{pkgdir}}{PROBE}"', (recipe / 'PKGBUILD').read_text())
        self.assertIn(PROBE.lstrip('/'), (PROJECT / 'desktop/build-sources').read_text())

    def test_gpu_desktop_opens_only_the_display_card(self):
        env = self.run_session(self.GPU)
        self.assertEqual(env['WLR_RENDERER'], 'gles2')
        self.assertEqual(env['WLR_RENDER_DRM_DEVICE'], '/dev/dri/renderD128')
        self.assertEqual(env['WLR_DRM_DEVICES'], '/dev/dri/card1')
        self.assertEqual(env['MESA_LOADER_DRIVER_OVERRIDE'], 'zink')
        self.assertNotIn('LIBGL_ALWAYS_SOFTWARE', env)
        self.assertNotIn('LIBVA_DRIVER_NAME', env)
        self.assertNotIn('MOZ_DISABLE_RDD_SANDBOX', env)

    def test_decoder_without_gpu_keeps_firefox_sandboxed(self):
        # A software desktop: VA-API applications get the decoder, Firefox (software-drawn) keeps its sandbox.
        env = self.run_session(self.DECODER)
        self.assertEqual(env['LIBVA_DRIVER_NAME'], 'v4l2_request')
        self.assertEqual(env['WLR_RENDERER'], 'pixman')
        self.assertNotIn('MOZ_DISABLE_RDD_SANDBOX', env)
        # The same holds on a board whose GPU fails the probe.
        env = self.run_session({**self.GPU, **self.DECODER}, probe='exit 1')
        self.assertEqual((env['LIBVA_DRIVER_NAME'], env['WLR_RENDERER']), ('v4l2_request', 'pixman'))
        self.assertNotIn('MOZ_DISABLE_RDD_SANDBOX', env)

    def test_decoder_on_the_gpu_desktop(self):
        env = self.run_session({**self.GPU, **self.DECODER})
        self.assertEqual((env['LIBVA_DRIVER_NAME'], env['MOZ_DISABLE_RDD_SANDBOX']), ('v4l2_request', '1'))

    def test_firefox_defaults_follow_the_session(self):
        config = (PROJECT / 'desktop/configuration/firefox.cfg').read_text()
        self.assertTrue(config.startswith('//'))  # AutoConfig skips the first line
        condition = 'if (getenv("MOZ_DISABLE_RDD_SANDBOX") == "1" && getenv("LIBVA_DRIVER_NAME") == "v4l2_request") {'
        self.assertIn(condition, config)
        # Every preference sits inside that condition, as a default the user can change.
        body = config[config.index(condition):]
        self.assertEqual(config.count('Pref('), body.count('defaultPref('))


if __name__ == '__main__':
    unittest.main()
