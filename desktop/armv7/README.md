# ARMv7 desktop components

`desktop/build --architecture armv7h` builds the same desktop payload for an
ARMv7 Arch Linux ARM userspace: the pinned Omarchy UI and the keyboard, compiled
for ARMv7. No package is built: the image installs `wlroots0.20`, `labwc`,
`omafox`, `omactivity`, `folio-touch` (Files) and `omacalc` from the ARMv7 channel of the
[Orchard package repository](https://github.com/OrchardLinux/packages)
(`repo-armv7h`), listed before Arch Linux ARM's repositories. Upstream Omarchy
publishes no ARMv7 packages, so an ARMv7 image has no `[omarchy]` repository
and Omacalc is the Orchard repository's build of upstream's pinned source.
Mesa is Arch Linux ARM's there.

A provisioned native ARMv7 Arch Linux ARM environment can run the recipes with
`ORCHARD_BUILD_NATIVE=1` and `ORCHARD_BUILD_ENV_ID` set to its reproducible image
identity. Orchard's ARMv7 build environment support is required. Container
builds take `--builder-image IMAGE`, naming an ARMv7 Arch Linux ARM compiler
with the dependencies from `desktop/install-toolchain`. The same option is
accepted by the component builders. The
repository's pinned AArch64 container is selected by AArch64 builds.

`system/build-armv7-builder` prepares that compiler image from the official
Arch Linux ARM bootstrap pinned in `system/armv7/bootstrap.json`: one dated
build, fetched from its copy in this repository's releases (upstream only
publishes a "latest" that it replaces), else from upstream while that is still
the same build. It verifies the archive's SHA-256 and detached signature
against Arch Linux ARM's build key before importing it. The selected Podman connection must already support
ARM32 execution. An emulator is a host prerequisite; the recipe leaves its
registration and the default connection to the person managing the host.

```sh
system/build-armv7-builder --receipt out/armv7-builder.json
python3 tools/build.py --orchard /path/to/orchard --platform apple-armv7 \
  --version armv7-development --output out/armv7-development
```

For an isolated builder, pass `--connection NAME` to the compiler recipe and
set `CONTAINER_CONNECTION=NAME` for the release build. The compiler receipt
records its image ID and installed package versions. Component cache keys
include the target architecture and the selected compiler image ID.

`tools/build.py` uses `localhost/omarchy-a-arch-builder:armv7h`, what this
recipe makes, unless `--builder-image` names another.

Each release contains one userspace ISA. Selecting `apple-armv7` chooses
`armv7h`; mixing it with AArch64 platforms is rejected before components
build. The release is the root as a block image with orchard's 32-bit
platform layer, loaders and install tools, like the arm64 one; orchard's
inputs supply its armv7 static tools (BusyBox, Dropbear).

The producers check the compiler's machine and the resulting ELF headers.
Package verification checks `.PKGINFO` and the ELF headers inside each package,
including the ARM EABI5 hard-float flags. Each component receipt records the
userspace architecture, and the release refuses a component, base or static
tool of another one.

An ARMv7 release requires a full component build and desktop smoke check
before hardware qualification. Tests of the architecture guards use
synthetic packages and executable headers.
