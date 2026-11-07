"""Userspace targets and executable checks shared by the release producers."""
from pathlib import Path
import struct
import tomllib


TARGETS = {
    'aarch64': {'orchard': 'arm64', 'machine': 'aarch64', 'class': 2, 'elf_machine': 183},
    'armv7h': {'orchard': 'arm', 'machine': 'armv7l', 'class': 1, 'elf_machine': 40},
}


def validate(architecture):
    if architecture not in TARGETS:
        raise ValueError(f'Unsupported userspace architecture: {architecture}')
    return architecture


def orchard_arch(architecture):
    return TARGETS[validate(architecture)]['orchard']


def machine(architecture):
    return TARGETS[validate(architecture)]['machine']


def podman_arch(architecture):
    return orchard_arch(architecture)


def platform_arch(platform, snapshot=None):
    """The userspace ISA for PLATFORM, checked against its Orchard descriptor."""
    if snapshot is not None:
        if not isinstance(platform, str) or '/' in platform or platform in ('', '.', '..'):
            raise ValueError('Invalid platform name')
        path = Path(snapshot) / 'platforms' / (platform + '.toml')
        arch = tomllib.loads(path.read_text())['kernel']['arch']
        for name, target in TARGETS.items():
            if target['orchard'] == arch:
                return name
        raise ValueError(f'{platform}: unsupported kernel architecture {arch}')
    known = {'apple-16k': 'aarch64', 'apple-4k': 'aarch64', 'apple-armv7': 'armv7h'}
    if platform not in known:
        raise ValueError(f'Unknown platform architecture: {platform}')
    return known[platform]


def check_elf(data, architecture, label='binary', *, executable=True):
    """Require an executable/shared ELF for the selected ISA and hard-float ABI."""
    target = TARGETS[validate(architecture)]
    if isinstance(data, (str, Path)):
        with Path(data).open('rb') as stream:
            data = stream.read(64)
    minimum = 64 if target['class'] == 2 else 52
    if (len(data) < minimum or data[:4] != b'\x7fELF' or
            data[4] != target['class'] or data[5:7] != b'\x01\x01'):
        raise ValueError(f'{label}: expected little-endian {architecture} ELF')
    kind, elf_machine, version = struct.unpack_from('<HHI', data, 16)
    if kind not in ((2, 3) if executable else (1, 2, 3)) or elf_machine != target['elf_machine'] or version != 1:
        raise ValueError(f'{label}: executable architecture differs from {architecture}')
    header_size = struct.unpack_from('<H', data, 52 if target['class'] == 2 else 40)[0]
    if header_size != minimum:
        raise ValueError(f'{label}: invalid ELF header size')
    if architecture == 'armv7h':
        flags = struct.unpack_from('<I', data, 36)[0]
        if flags >> 24 != 5 or (kind != 1 and (not flags & 0x400 or flags & 0x200)):
            raise ValueError(f'{label}: expected ARM EABI5 hard-float executable')
    return architecture
