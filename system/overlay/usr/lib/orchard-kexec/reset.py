"""Reset guard contract shared by installed and diagnostic warm handovers."""
from pathlib import Path


def backend():
    mode = Path('/sys/kernel/reboot/mode')
    # The standard ABI alone exists on unguarded kernels too. Require the
    # watchdog's binding, not an unrelated property elsewhere in the tree.
    for node in Path('/proc/device-tree').rglob('apple,tethered-boot'):
        compatible = node.parent / 'compatible'
        status = node.parent / 'status'
        if (compatible.exists() and b'apple,wdt' in compatible.read_bytes().split(b'\0')
                and (not status.exists() or status.read_bytes().rstrip(b'\0') in (b'ok', b'okay'))
                and mode.exists()):
            return mode, 'reboot-mode'
    old = Path('/sys/module/apple_wdt/parameters/cold_restart')
    if old.exists():
        return old, 'cold_restart'
    raise ValueError('running kernel lacks the cold reset guard')


def select(warm=True):
    knob, abi = backend()
    value = ('warm' if warm else 'cold') if abi == 'reboot-mode' else ('N' if warm else 'Y')
    knob.write_text(value + '\n')
    if knob.read_text().strip() != value:
        raise ValueError('could not select guarded reset mode')
    return f'{abi}={value}'


def status():
    knob, abi = backend()
    return f'{abi}={knob.read_text().strip()}'
