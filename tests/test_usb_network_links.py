"""The installed system's USB network comes back with usb0, not only at boot."""
import pathlib
import unittest

from release import audit

ROOT = pathlib.Path(__file__).resolve().parents[1]

UNIT = '/usr/lib/systemd/system/orchard-usb-network.service'
WANTS = 'etc/systemd/system/'
REQUIRED_FILES = ('usr/bin/dropbear', 'usr/lib/orchard/busybox', 'etc/orchard/udhcpd.conf',
                  'usr/lib/systemd/system/orchard-ssh.service',
                  'usr/lib/systemd/system/orchard-usb-network.service')


def links(**drop):
    found = {WANTS + 'getty.target.wants/serial-getty@ttyGS0.service':
                 (True, '/usr/lib/systemd/system/serial-getty@.service'),
             WANTS + 'multi-user.target.wants/orchard-ssh.service':
                 (True, '/usr/lib/systemd/system/orchard-ssh.service'),
             WANTS + 'multi-user.target.wants/orchard-usb-network.service': (True, UNIT),
             WANTS + 'sys-subsystem-net-devices-usb0.device.wants/orchard-usb-network.service': (True, UNIT)}
    for name in drop:
        del found[WANTS + name.replace('__', '/')]
    return found


class UsbNetworkLinks(unittest.TestCase):
    def test_unit_follows_usb0(self):
        unit = (ROOT / 'system/overlay' / UNIT.lstrip('/')).read_text()
        self.assertIn('BindsTo=sys-subsystem-net-devices-usb0.device', unit)
        self.assertIn('sys-subsystem-net-devices-usb0.device', unit.split('[Install]', 1)[1])

    def test_audit_requires_the_usb0_link(self):
        hashes = dict.fromkeys(REQUIRED_FILES, 'x')
        audit.verify_reachable(hashes, links())
        with self.assertRaisesRegex(ValueError, 'usb0.device.wants'):
            audit.verify_reachable(
                hashes, links(**{'sys-subsystem-net-devices-usb0.device.wants__orchard-usb-network.service': 1}))


if __name__ == '__main__':
    unittest.main()
