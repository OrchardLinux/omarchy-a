"""Exercise compositor release semantics with virtual input, never hardware."""
import json
from pathlib import Path
import subprocess
import time

MARKS = Path('/run/user/1000/launcher-marks')
WTYPE = '/usr/libexec/omarchy-wtype'


def count():
    return len(MARKS.read_text().splitlines()) if MARKS.exists() else 0


def keys(*args):
    subprocess.run([WTYPE, *args], check=True, timeout=5)


def expect(expected):
    deadline = time.monotonic() + 2
    while count() != expected and time.monotonic() < deadline:
        time.sleep(.02)
    assert count() == expected, (count(), expected)


def unchanged(expected):
    # Observe a quiet window after the input sequence and async Execute dispatch.
    deadline = time.monotonic() + .25
    while time.monotonic() < deadline:
        assert count() == expected, (count(), expected)
        time.sleep(.02)


def record(name):
    print(json.dumps({'case': name, 'passed': True, 'launcher_count': count()}), flush=True)


MARKS.unlink(missing_ok=True)
for index, key in enumerate(('Super_L', 'Super_R', 'XF86HomePage'), 1):
    keys('-k', key)
    expect(index)
    record(key + '-tap')

for key in ('c', 'x', 'Escape'):
    keys('-P', 'Super_L', '-M', 'logo', '-k', key, '-m', 'logo', '-p', 'Super_L')
    unchanged(3)
    record('Cmd+' + key)

held = subprocess.Popen([WTYPE, '-P', 'XF86HomePage', '-s', '700', '-p', 'XF86HomePage'])
time.sleep(.2)
assert held.poll() is None
unchanged(3)
held.wait(timeout=5)
expect(4)
record('Home-release-only')

held = subprocess.Popen([WTYPE, '-P', 'Super_L', '-M', 'logo', '-s', '700', '-m', 'logo', '-p', 'Super_L'])
time.sleep(.2)
subprocess.run(['/tmp/pointer-helper', 'pointer', 'click', 'left'], check=True, timeout=5)
held.wait(timeout=5)
unchanged(4)
record('Cmd+click')
