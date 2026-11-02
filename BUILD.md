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
change; the release is assembled and audited every time. `orchard run` then boots
its recovery on the attached device without installing, and `orchard install`
installs it. The rest of this page is what that entry runs, step by step.

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
- `python boot/build-artwork --output DIR`: the Omarchy mark as data for orchard's m1n1: `splash` (480 px, painted by m1n1 for an installed boot entry) and `logo.bin` (m1n1's custom logo payload, 256 and 128 px, shown by the recovery). No m1n1 is built here; releases boot orchard's, `quiet/m1n1.bin` from the component bundle.
- Pongo is not built here. Releases ship orchard's one Pongo, `quiet/pongo.bin` from the orchard component bundle (black screen; the logo appears with m1n1).

Retain each component's receipt. Do not change hardware activation or timing as part of presentation changes.

## Assemble

The following example uses distro-owned components collected under `out/components/`.
A release covers every platform: one root image, and per platform a recovery
(`recovery-PLATFORM.bin`) and orchard's platform layer (`platform-PLATFORM.tar.gz`:
kernel, every board's DTB, modules), which the installer writes into the root.
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
  --loader out/components/quiet/m1n1.bin \
  --splash out/components/artwork/splash \
  --logo out/components/artwork/logo.bin \
  --pongo out/components/quiet/pongo.bin \
  --busybox out/components/boot/busybox \
  --dropbear out/components/boot/dropbear \
  --dropbearkey out/components/boot/dropbearkey \
  --wpa-supplicant out/components/boot/wpa_supplicant \
  --wpa-cli out/components/boot/wpa_cli \
  --iw out/components/boot/iw \
  --cursor-tools out/components/desktop/cursor-tools \
  --bluetooth-tools out/components/desktop/bluetooth-tools \
  --labwc-tools out/components/desktop/labwc-tools \
  --output out/releases/0.1.0-orchard.3
```

To use a staged kernel bundle instead (as CI does with orchard's published
component bundles), pass `--kernel-dir PLATFORM=DIRECTORY` per platform; the
others still come from `--inputs`, and without `--inputs` the given bundles are
the release's platforms. `--platform PLATFORM` builds only that
platform, for development; a release covers every platform. Each recovery carries
the DTB of every board of its platform; m1n1 boots with the one matching the
device. The cache respects `XDG_CACHE_HOME` and `ORCHARD_CACHE_DIR`, just like RAM
builds.

Choose a new version and output directory for each build. Root builds first; recoveries embed its exact stream receipt, and `release.toml` and the index are written last. The installed root carries no Orchard device runtime: it boots directly from the boot entry orchard's installer writes.

## Validate without a device

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
python -m release.audit out/releases/0.1.0-orchard.3/release.toml
PYTHONPATH=$ORCHARD_CHECKOUT/src python -m orchard.manifests --verify-local out/releases/0.1.0-orchard.3/index.toml
```

The auditor verifies, per platform, the recovery's contents, endpoints and loader framing, orchard's layer against its receipt and SHA256SUMS, and that recovery and layer carry the same modules; for the root, desktop/privilege policy, that it holds no file of any layer, and the absence of private session/firmware data.

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
