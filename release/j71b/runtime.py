"""Distro composition of independent hardware runtime plus image-owned policy."""
from pathlib import Path
from orchard_hardware.image.runtime import files as hardware_files

PROJECT = Path(__file__).resolve().parents[2]


def files(modules_dir):
    return hardware_files(modules_dir, PROJECT / 'image/j71b')
