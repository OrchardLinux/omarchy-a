"""Run the public userspace headlessly in Podman; never access an iPad."""
import argparse
import json
from pathlib import Path
import subprocess

from .audit import audit
from release.devices import device as device_spec
from release.manifests import read_release


def main(device='j71b'):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='new evidence directory')
    parser.add_argument('--pointer-helper', type=Path, help='optional native wlrctl binary for virtual pointer validation')
    parser.add_argument('--image', default='localhost/orchard-hardware-kernel-toolchain:bookworm')
    args = parser.parse_args()
    manifest = args.manifest.resolve()
    if args.pointer_helper and not args.pointer_helper.is_file():
        parser.error('Pointer helper must be a native wlrctl executable file')
    if args.output.exists():
        parser.error('Choose a new evidence directory')
    # Verify namespace safety and all published digests before using GNU tar.
    checked = audit(manifest, device)
    record = read_release(manifest)
    args.output.mkdir(parents=True)
    output = args.output.resolve()
    recipe = Path(__file__).with_name('smoke-desktop-in-container').resolve()
    argv = ['podman', 'run', '--rm', '--network', 'none', '--userns', 'keep-id:uid=0,gid=0',
            '--cap-add', 'SYS_ADMIN', '--cap-add', 'SYS_PTRACE', '--security-opt', 'seccomp=unconfined',
            '-e', 'OMA_ROOT_FILENAME=' + record['assets']['root']['file'],
            '-e', 'OMA_PROFILE=' + device, '-e', 'OMA_BACKLIGHT=' + device_spec(device)['backlight'],
            '-v', str(manifest.parent) + ':/release:ro', '-v', str(recipe) + ':/validate.sh:ro',
            '-v', str(output) + ':/evidence:rw', args.image, 'sh', '/validate.sh']
    if args.pointer_helper:
        argv[-3:-3] = ['-v', str(args.pointer_helper.resolve()) + ':/pointer-helper:ro']
    with (output / 'native.log').open('wb') as log:
        result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT)
    passed = False
    if result.returncode == 0:
        status = json.loads((output / 'status.json').read_text())['result']
        passed = (status['ready'] is True and status['release'] == record['release'] and
                  (output / 'desktop.png').stat().st_size > 0 and
                  'percentage\t73%' in (output / 'battery.txt').read_text() and
                  'PASSWORDLESS_SUDO_OK' in (output / 'sudo.txt').read_text() and
                  'POWER_KEY_BACKLIGHT_ROUND_TRIP_OK' in (output / 'power-key-toggle.txt').read_text())
    verdict = {'passed': passed, 'hardware_validated': False, 'release': record['release'],
               'root_sha256': checked['root_sha256'], 'scope': 'headless userspace, not iPad kernel/input',
               'battery_fixture_percent': 73, 'backlight_fixture': True,
               'passwordless_sudo_test': True, 'power_key_toggle_test': True,
               'screenshot_requires_visual_review': True,
               'virtual_pointer_test': bool(args.pointer_helper)}
    (output / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
    if not passed:
        parser.exit(1, 'Native desktop validation failed; inspect ' + str(output) + '\n')
    print(json.dumps(verdict, indent=2))


if __name__ == '__main__':
    main()
