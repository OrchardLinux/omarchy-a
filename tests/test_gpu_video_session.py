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


class G5PSession(unittest.TestCase):
    """The iPad 5: the private stack, a passing probe and the ADBE card decide the GPU desktop."""
    G5P = {'drm/renderD128': ('soc/gpu', 'apple-g5p-drm'), 'drm/card0': ('soc/gpu', 'apple-g5p-drm'),
           'drm/card1': ('soc/display', 'apple-adbe'), 'drm/card1-eDP-1': ('soc/display/drm/card1', 'none')}
    PREFIX = '/opt/orchard/g5p'

    def run_session(self, devices, probe_rc=0, stack=True, inherited=''):
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
            prefix = root / self.PREFIX.lstrip('/')
            if stack:
                for path in ('share/vulkan/icd.d/powervr_mesa_icd.aarch64.json', 'lib/libEGL_mesa.so.0'):
                    (prefix / path).parent.mkdir(parents=True, exist_ok=True)
                    (prefix / path).touch()
                probe = prefix / 'libexec/omarchy-g5p-probe'
                probe.parent.mkdir(parents=True)
                probe.write_text('#!/bin/sh\necho "$@" >"$FAKE/probe-args"\n'
                                 'env | sort >"$FAKE/probe-env"\nexit %d\n' % probe_rc)
                probe.chmod(0o755)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            (bin_dir / 'timeout').write_text('#!/bin/sh\nshift 3\nexec "$@"\n')  # timeout -k 2 12 cmd...
            (bin_dir / 'timeout').chmod(0o755)
            (root / 'run').mkdir()
            block = detection().replace(self.PREFIX, '"$FAKE"' + self.PREFIX)
            script = ('set -euo pipefail\nexport WLR_RENDERER=pixman LIBGL_ALWAYS_SOFTWARE=1\n' + inherited +
                      block + '\nenv | grep -E "^(WLR_|MESA_|GALLIUM_|PVR_|LIBGL_|OMARCHY_G5P|VK_|GBM_)" | sort')
            env = {'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'FAKE': str(root), 'XDG_RUNTIME_DIR': str(root / 'run')}
            result = subprocess.run(['bash', '-c', script], env=env, text=True, capture_output=True, check=True)
            exported = dict(line.split('=', 1) for line in result.stdout.splitlines())
            args = (root / 'probe-args').read_text().split() if (root / 'probe-args').exists() else None
            probe_env = (root / 'probe-env').read_text().splitlines() if (root / 'probe-env').exists() else []
            return exported, args, probe_env, result.stderr

    SOFTWARE = {'WLR_RENDERER': 'pixman', 'LIBGL_ALWAYS_SOFTWARE': '1'}

    def test_gpu_desktop_after_a_passing_probe(self):
        env, args, probe_env, _ = self.run_session(self.G5P)
        self.assertEqual(args, ['/dev/dri/renderD128', '/dev/dri/card1'])
        self.assertEqual(env['OMARCHY_G5P'], '1')
        self.assertEqual(env['WLR_RENDERER'], 'gles2')
        self.assertEqual(env['WLR_BACKENDS'], 'drm,libinput')
        self.assertEqual(env['WLR_DRM_DEVICES'], '/dev/dri/card1')
        self.assertEqual(env['WLR_RENDER_DRM_DEVICE'], '/dev/dri/renderD128')
        self.assertEqual(env['WLR_SCENE_DISABLE_DIRECT_SCANOUT'], '1')
        self.assertTrue(env['VK_DRIVER_FILES'].endswith(self.PREFIX + '/share/vulkan/icd.d/powervr_mesa_icd.aarch64.json'))
        # Mesa's own routing (kmsro for ADBE, Zink for G5P): no override for Labwc or its clients.
        for name in ('MESA_LOADER_DRIVER_OVERRIDE', 'GALLIUM_DRIVER', 'LIBGL_ALWAYS_SOFTWARE'):
            self.assertNotIn(name, env)
        # The probe ran with the stack Labwc gets, and without an override.
        self.assertTrue(any(line.startswith('VK_DRIVER_FILES=') for line in probe_env))
        self.assertFalse(any(line.startswith(('MESA_LOADER_DRIVER_OVERRIDE=', 'GALLIUM_DRIVER=',
                                              'LIBGL_ALWAYS_SOFTWARE=')) for line in probe_env))

    def test_inherited_override_is_dropped(self):
        env, _, probe_env, _ = self.run_session(
            self.G5P, inherited='export MESA_LOADER_DRIVER_OVERRIDE=zink GALLIUM_DRIVER=zink\n')
        self.assertNotIn('MESA_LOADER_DRIVER_OVERRIDE', env)
        self.assertNotIn('GALLIUM_DRIVER', env)
        self.assertFalse(any(line.startswith('MESA_LOADER_DRIVER_OVERRIDE=') for line in probe_env))

    def test_failed_probe_keeps_the_software_desktop(self):
        env, args, _, stderr = self.run_session(self.G5P, probe_rc=1)
        self.assertEqual(args, ['/dev/dri/renderD128', '/dev/dri/card1'])
        self.assertEqual(env, self.SOFTWARE)
        self.assertIn('G5P probe failed', stderr)

    def test_missing_stack_or_display_keeps_the_software_desktop(self):
        env, args, _, _ = self.run_session(self.G5P, stack=False)
        self.assertEqual((env, args), (self.SOFTWARE, None))
        no_display = {k: v for k, v in self.G5P.items() if not k.startswith('drm/card1')}
        env, args, _, _ = self.run_session(no_display)
        self.assertEqual((env, args), (self.SOFTWARE, None))

    def test_display_card_is_chosen_by_driver(self):
        # A later card that is not ADBE (another KMS-less device) must not win.
        devices = {**self.G5P, 'drm/card2': ('soc/other', 'other-drm')}
        env, args, _, _ = self.run_session(devices)
        self.assertEqual(args[1], '/dev/dri/card1')
        self.assertEqual(env['WLR_DRM_DEVICES'], '/dev/dri/card1')


if __name__ == '__main__':
    unittest.main()
