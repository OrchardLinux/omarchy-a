"""Distro composition of independent hardware runtime plus image-owned policy."""
from pathlib import Path
from orchard_hardware.image.runtime import files as hardware_files

PROJECT = Path(__file__).resolve().parents[2]


def files(modules_dir, profile='j71b'):
    policy = PROJECT / 'image' / profile
    if profile == 'j71b':
        # Hardware releases before multi-device support take no profile.
        return hardware_files(modules_dir, policy)
    return hardware_files(modules_dir, policy, profile=profile)
