"""Desktop build targets, checked against component bytes and package metadata."""
from pathlib import Path
import json
import platform
import subprocess
import sys
import tarfile

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
from release.architecture import validate, check_elf, machine, podman_arch


def source_pins(architecture):
    validate(architecture)
    here = Path(__file__).resolve().parent
    pins = json.loads((here / 'sources.json').read_text())
    if architecture == 'armv7h':
        pins.update(json.loads((here / 'armv7/sources.json').read_text()))
    return pins


def builder(buildenv, architecture, image=None, *, labwc=False):
    validate(architecture)
    if buildenv.native():
        if platform.machine() != machine(architecture):
            raise ValueError('Native compiler architecture differs from ' + architecture)
        return image or 'native:' + architecture
    if image:
        return image
    if architecture == 'armv7h':
        raise ValueError('ARMv7 desktop builds require --builder-image with an ARMv7 Arch Linux ARM compiler')
    here = Path(__file__).resolve().parent
    image = 'localhost/omarchy-a-' + ('labwc' if labwc else 'desktop') + '-builder:arm64'
    folder = here / 'labwc' if labwc else here
    buildenv.build(image, folder / 'Containerfile', folder, arch=podman_arch(architecture))
    return image


def check_package(path, architecture):
    """A package's signed/hash-checked bytes must name the selected target."""
    validate(architecture)
    result = subprocess.run(['bsdtar', '-xOf', str(path), '.PKGINFO'], check=True,
                            text=True, capture_output=True, timeout=30)
    values = [line.removeprefix('arch = ') for line in result.stdout.splitlines() if line.startswith('arch = ')]
    if values != [architecture]:
        raise ValueError('Package architecture differs from ' + architecture + ': ' + str(path))
    # Re-stream the package as tar so Python versions without zstd support
    # inspect ELF headers without extracting files onto the host.
    process = subprocess.Popen(['bsdtar', '-cf', '-', '@' + str(Path(path).resolve())],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        expanded = count = 0
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for member in archive:
                count += 1
                expanded += member.size
                if count > 100000 or expanded > (1 << 30):
                    raise ValueError('Desktop package exceeds its inspection bound')
                if member.isfile():
                    with archive.extractfile(member) as source:
                        header = source.read(64)
                    if header.startswith(b'\x7fELF'):
                        check_elf(header, architecture, member.name)
        process.stdout.close()
        if process.wait(timeout=30):
            raise ValueError('Desktop package could not be inspected')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
    return architecture
