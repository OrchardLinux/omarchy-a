"""The builder of the omarchy-a package for an image: the pinned Arch Linux ARM container, or native CI."""
from pathlib import Path
import platform
import sys

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
from release.architecture import validate, machine, podman_arch  # noqa: F401 (podman_arch: callers)


def builder(buildenv, architecture, image=None):
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
    image = 'localhost/omarchy-a-desktop-builder:arm64'
    buildenv.build(image, here / 'Containerfile', here, arch=podman_arch(architecture))
    return image
