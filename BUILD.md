# Build Omarchy A

## GitHub Actions

`.github/workflows/build.yml` runs unit tests on pull requests and `main`. Version tags (`v*`) and manual dispatches additionally generate the loader artwork on macOS, build m1n1 on Linux ARM64, and the signed Arch Linux ARM userspace on a native ARM64 worker using the same pinned Arch job image and `install-toolchain` recipes as local builds. Source packages build as an unprivileged user; rootfs package assembly runs as root in the disposable job. No nested Podman is used. Shared recipe path variables select actual CI paths instead of container mounts. Native execution is not a security or network sandbox.

`ci/dependencies` checks out orchard's `main` (or `ORCHARD_REF`) and verifies the compiled component bundle of a published orchard release. Select the release tag of the components during manual dispatch; tag builds use the explicit default in the workflow. The release receipt records the exact orchard commit that built it.

Assembly runs the same producers, artifact auditor, CLI resolution and publication staging as local builds. Version tags create **draft** releases; manual builds only retain workflow artifacts for seven days. Nothing automatically announces a release or operates a device. Follow the [release order](https://github.com/OrchardLinux/orchard/blob/main/docs/ci.md), then qualify fresh installation and cold-restart launch on hardware.

## With orchard

```sh
orchard build [--version VERSION]
```

builds a release into `out/releases/VERSION` (default `dev-DATE-TIME`) through
`tools/build.py`, the entry `orchard.toml` names: each component below is kept in
`out/components/NAME/KEY/`, keyed by its files, and rebuilt only when they
change; the release is assembled and audited every time. `orchard run` starts
the selected kernel on the attached device and `orchard install` installs the
release. `orchard build --platform apple-armv7` builds the 32-bit (armv7h)
release instead. The rest of this page describes the producer steps.

## Local setup

Run commands from this repository. Requires uv, `zstd`, and a native ARM64 Podman
environment for image/component builds.

## Set up build tools

```sh
orchard --version
```

`orchard` comes from orchard's launcher on your PATH and runs orchard's newest
nightly (`ORCHARD_VERSION` pins one); an orchard checkout's own `bin/orchard` runs
that checkout. This build imports none of orchard's Python: it runs orchard's
producers as commands from an orchard snapshot (orchard
[docs/distribution-contract.md](https://github.com/OrchardLinux/orchard/blob/main/docs/distribution-contract.md)),
which `orchard build` names in `ORCHARD_CHECKOUT`. Without orchard, set
`ORCHARD_CHECKOUT` (or pass `--orchard DIR`) to an orchard checkout or a
release's `orchard-source.tar.gz` unpacked, and run the steps below with any
Python 3.11.

## Produce components

- `desktop/build-sources` and `desktop/build`: desktop applications and payload.
- `system/build-rootfs`: signed Arch Linux ARM base and package receipt; see [system/README.md](system/README.md).
- orchard supplies the kernel, DTBs and modules of every platform, its platform layer, and the static BusyBox/Dropbear recipes; see [orchard's build instructions](https://github.com/OrchardLinux/orchard/blob/main/BUILD.md). Local assembly builds or reuses each platform's kernel through orchard's shared cache. Build the static tools separately; supply explicit kernel bundles only when overriding that default.
- `python boot/build-artwork --output DIR`: the Omarchy mark: `splash` (480 px, painted for an installed boot entry) and `logo.bin` (256 and 128 px).
- No loader is built here: a release names orchard's loaders as orchard's index lists them (arm64: Pongo and m1n1).

Retain each component's receipt. Do not change hardware activation or timing as part of presentation changes.

## Assemble

The following example uses distro-owned components collected under `out/components/`.
A release has one root of one userspace architecture, and the same shape for
both: the root as a block image (`root.blocks.zst`, `root.map.json`), its logo,
and orchard's platform layers, loaders and install tools, which
`orchard.image.platforms_index` supplies from orchard's index of that
architecture (`platforms.toml` for arm64, the separate 32-bit index for
armv7h). No recovery image is part of a release.
The kernels come from the same orchard builder and cache as `orchard build` in
orchard's examples; matching inputs reuse the compiled bundles. Boot artwork,
userspace and assembly remain owned by this repository; the m1n1 is orchard's.
First what orchard supplies finished, as one JSON file (kernel bundles, boards,
m1n1, Pongo, tools; the nightly's when they match):

```sh
PYTHONPATH=$ORCHARD_CHECKOUT/src python -m orchard.inputs --output out/inputs.json
python -m release.build \
  --release 0.1.0-orchard.3 \
  --inputs out/inputs.json \
  --base out/components/base/rootfs.tar.gz \
  --base-receipt out/components/base/rootfs.tar.gz.json \
  --splash out/components/artwork/splash \
  --logo out/components/artwork/logo.bin \
  --busybox out/components/boot/busybox \
  --dropbear out/components/boot/dropbear \
  --dropbearkey out/components/boot/dropbearkey \
  --cursor-tools out/components/desktop/cursor-tools \
  --bluetooth-tools out/components/desktop/bluetooth-tools \
  --labwc-tools out/components/desktop/labwc-tools \
  --output out/releases/0.1.0-orchard.3
```

To use a staged kernel bundle, pass `--kernel-dir PLATFORM=DIRECTORY` to
`orchard.inputs`. Select a subset there with `--platform PLATFORM`; the index
consumes that document's exact selection. `release.build --orchard-release TAG`
takes finished AArch64 files from a published Orchard build and accepts
`--platform PLATFORM` to select its layers. `--architecture armv7h` builds the
32-bit release; from a published build it names its platforms
(`--platform apple-armv7`). The cache respects `XDG_CACHE_HOME`
and `ORCHARD_CACHE_DIR`, just like RAM builds.

Choose a new version and output directory for each build. Root builds first,
then orchard's files and the block image; `release.toml` and the index are
written last. The cached base retains `base-<desktop-key>` in
`etc/ipadlinux/release`; `etc/orchard/release.json` identifies the final
release.

For the ARMv7 compiler and build, see
[ARMv7 desktop components](desktop/armv7/README.md). Building the armv7h
desktop and base runs ARMv7 code: the builder image needs a Podman connection
that executes ARM32 binaries (emulated on an arm64 host, 1 to 3 hours). The
release step itself runs only arm64 tools.

## Validate without a device

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
python -m release.audit out/releases/0.1.0-orchard.3/release.toml
PYTHONPATH=$ORCHARD_CHECKOUT/src python -m orchard.manifests --verify-local out/releases/0.1.0-orchard.3/index.toml
```

The auditor checks the block image, map, logo, loaders and install tools, the
platform layers against their receipts and SHA256SUMS, desktop integrity,
package privileges, that the desktop helpers are of the root's architecture,
and the absence of private session and firmware data.

Headless finished-artifact checks use Podman without network or device passthrough:

```sh
python -m release.smoke_desktop \
  --manifest out/releases/0.1.0-orchard.3/release.toml \
  --output out/validation/desktop \
  --pointer-helper out/components/validation/wlrctl
python desktop/test-input --artifact-only \
  --manifest out/releases/0.1.0-orchard.3/release.toml \
  --output out/validation/input \
  --pointer-helper out/components/validation/wlrctl
```

Choose new evidence directories. `wlrctl` is a test-only native AArch64 helper, not installed in the image; both tests can run without it. They use `localhost/orchard-hardware-kernel-toolchain:bookworm`, built from the hardware package's kernel Containerfile. Native SSH/NSS regression uses the Arch builder image from this repository's base producer.

`tools/with-source-denied --deny PATH [--allow INPUT_DIRECTORY] -- COMMAND...` optionally verifies that a command does not read a source checkout.

## Publish

Follow [Publishing Omarchy A](docs/releasing.md). Build/audit success is not physical-device qualification: test a fresh installation and a cold-restart `orchard launch` on supported hardware before announcing the release. The experimental desktop auto-logs in at boot and has no disk encryption; this is disclosed in the README and must not be described as a secure daily-use system.
