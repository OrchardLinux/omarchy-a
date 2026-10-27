"""Per-device composition facts. Desktop, installer and audit code stays shared."""

# J71b artifact names predate multi-device releases and stay unchanged. Other
# devices prefix their device-specific files so one release can carry several.
DEVICES = {
    'j71b': {'prefix': '', 'backlight': '20e200080.backlight',
             'helpers': ('j71b-check-platform', 'j71b-charge-lease'),
             'units': ('j71b-charge.service', 'omarchy-diagnostics.service')},
    # J71t charging policy is in the kernel; there is no userspace lease.
    'j71t': {'prefix': 'j71t-', 'backlight': '20e200000.backlight',
             'helpers': ('j71t-check-platform',),
             'units': ('omarchy-diagnostics.service',)},
}

# Device-independent files of the J71b system layer that later devices reuse.
SHARED_SYSTEM = (
    'etc/sudoers.d/90-tablet-passwordless',
    'etc/systemd/logind.conf.d/60-omarchy-a-power.conf',
    'etc/systemd/sleep.conf.d/60-omarchy-a-no-suspend.conf',
    'usr/lib/omarchy-bluetooth/policy.py',
    'usr/lib/systemd/system/omarchy-diagnostics.service',
    'usr/libexec/omarchy-bluetooth-pair',
    'usr/libexec/omarchy-desktop-ready',
    'usr/libexec/omarchy-diagnostics',
    'usr/libexec/omarchy-screen-toggle',
)


def device(profile):
    if profile not in DEVICES:
        raise ValueError('Unsupported Omarchy A device: ' + repr(profile))
    return DEVICES[profile]


def asset(profile, name):
    """Device-specific release file name. The branded Pongo is shared."""
    return name if name == 'pongo.bin' else device(profile)['prefix'] + name
