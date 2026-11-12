"""The login session picks the GPU and the video decoder from what the board has; software stays the default."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SESSION = PROJECT / 'desktop/configuration/login-session'
START, END = '# A board with a GPU', 'export PATH=/usr/local/bin:/usr/bin'


def detection():
    """The hardware block of the session, reading a fake /sys and printing what it exported."""
    text = SESSION.read_text()
    block = text[text.index(START):text.index(END)]
    return block.replace('/sys/', '"$FAKE"/sys/').replace(
        '-e /usr/share/vulkan/icd.d/powervr_mesa_icd.json', '-n ${ICD:-}')


class Session(unittest.TestCase):
    def run_session(self, devices, icd=True):
        """devices: {sysfs class path: (device path, driver name)}."""
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
            script = ('set -euo pipefail\nexport WLR_RENDERER=pixman LIBGL_ALWAYS_SOFTWARE=1\n' + detection() +
                      '\nenv | grep -E "^(WLR_|MESA_|PVR_|LIBGL_|LIBVA_|MOZ_)" | sort')
            env = {'PATH': os.environ['PATH'], 'FAKE': str(root), **({'ICD': '1'} if icd else {})}
            result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True, check=True)
            return dict(line.split('=', 1) for line in result.stdout.splitlines())

    GPU = {'drm/renderD128': ('soc/gpu', 'powervr'), 'drm/card0': ('soc/gpu', 'powervr'),
           'drm/card1': ('soc/display', 'apple-adbe'), 'drm/card1-eDP-1': ('soc/display/drm/card1', 'none')}
    DECODER = {'video4linux/video0': ('soc/video-codec', 'apple-vxd')}

    def test_software_desktop_without_the_hardware(self):
        expected = {'WLR_RENDERER': 'pixman', 'LIBGL_ALWAYS_SOFTWARE': '1'}
        self.assertEqual(self.run_session({}), expected)
        # A display controller alone, or another driver's render node, is no reason to leave pixman.
        self.assertEqual(self.run_session({'drm/card0': ('soc/display', 'apple-adbe'),
                                           'drm/renderD128': ('soc/other', 'other-gpu')}), expected)
        # The kernel driver without this image's Vulkan driver cannot draw.
        self.assertEqual(self.run_session(self.GPU, icd=False), expected)

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
        # The iPad 5: VA-API applications get the decoder, Firefox (software-drawn) keeps its sandbox.
        env = self.run_session(self.DECODER)
        self.assertEqual(env['LIBVA_DRIVER_NAME'], 'v4l2_request')
        self.assertEqual(env['WLR_RENDERER'], 'pixman')
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
