# ARMv7 desktop components

`desktop/build --architecture armv7h` builds the same desktop payload for an
ARMv7 Arch Linux ARM userspace. The existing AArch64 signed Omacalc input
continues to serve AArch64 builds. ARMv7 builds compile Omacalc from the source
recorded in `sources.json`, with the recipe in `../packages/omacalc`.

The Omacalc archive is pinned to upstream v0.3.1, commit
`573d7106f5c6c0225864eb8634ae37ddcb657f63`. Its SHA-256 was measured from the
265,215-byte GitHub commit archive. The recipe installs upstream's MIT license
and the bundled font's OFL notice, and runs the upstream Qt tests offscreen.

A provisioned native ARMv7 Arch Linux ARM environment can run the recipes with
`ORCHARD_BUILD_NATIVE=1` and `ORCHARD_BUILD_ENV_ID` set to its reproducible image
identity. Orchard's ARMv7 build environment support is required. Container
builds take `--builder-image IMAGE`, naming an ARMv7 Arch Linux ARM compiler
with the dependencies from `desktop/install-toolchain` and
`desktop/labwc/install-toolchain`, plus `qt6-base`, `qt6-declarative` and
`qt6-tools`. The same option is accepted by the component builders. The
repository's pinned AArch64 container is selected by AArch64 builds.

`system/build-armv7-builder` prepares that compiler image from the official
Arch Linux ARM bootstrap pinned in `system/armv7/bootstrap.json`. It verifies
the archive's SHA-256 and detached signature against Arch Linux ARM's build
key before importing it. The selected Podman connection must already support
ARM32 execution. An emulator is a host prerequisite; the recipe leaves its
registration and the default connection to the person managing the host.

```sh
system/build-armv7-builder --receipt out/armv7-builder.json
python3 tools/build.py --orchard /path/to/orchard --device p105 \
  --builder-image localhost/omarchy-a-arch-builder:armv7h \
  --version armv7-development --output out/armv7-development
```

For an isolated builder, pass `--connection NAME` to the compiler recipe and
set `CONTAINER_CONNECTION=NAME` for the release build. The compiler receipt
records its image ID and installed package versions. Component cache keys
include the target architecture and the selected compiler image ID.

Each release contains one userspace ISA. Selecting `apple-armv7` chooses
`armv7h`; mixing it with AArch64 platforms is rejected before components
build. A Cascadia recovery also needs one selected board, because its loader
uses that board's handoff profile. Orchard's companion ARMv7 producer change
provides the loader and static tools through its per-platform input record.

The producers check the compiler's machine and the resulting ELF headers.
Package verification checks `.PKGINFO` and the ELF headers inside each package,
including the ARM EABI5 hard-float flags. Each component receipt records the
userspace architecture. A foreign package or executable stops assembly before
it reaches a root filesystem.

These source recipes require a full ARMv7 component build and desktop smoke
check before hardware qualification. Tests of the architecture guards use
synthetic packages and executable headers.
