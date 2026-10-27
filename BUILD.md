# Build Omarchy A

## GitHub Actions

`.github/workflows/build.yml` runs unit tests on pull requests and `main`. Version tags (`v*`) and manual dispatches additionally build Pongo/artwork on macOS, m1n1 on Linux ARM64, and the signed Arch Linux ARM userspace on a native ARM64 worker using the same pinned Arch job image and `install-toolchain` recipes as local builds. Source packages build as an unprivileged user; rootfs package assembly runs as root in the disposable job. No nested Podman is used. Shared recipe path variables select actual CI paths instead of container mounts. Native execution is not a security or network sandbox.

`ci/dependencies` installs a hashed, published CLI/hardware wheel pair and verifies the compiled hardware bundle. Select immutable dependency tags during manual dispatch; tag builds use explicit defaults in the workflow. Hardware code comes from the wheel, not a sibling checkout or an implicit `main` branch.

Assembly runs the same producers, artifact auditor, CLI resolution and publication staging as local builds. Version tags create **draft** releases; manual builds only retain workflow artifacts for seven days. Nothing automatically announces a release or operates a device. Follow the [release order](https://github.com/OrchardLinux/hardware/blob/main/docs/ci.md), then qualify fresh installation and cold-restart launch on hardware.

## Local setup

Run commands from this repository. Requires Python 3.9+ with venv/pip, `zstd`, and a native ARM64 Podman environment for image/component builds.

## Set up build tools

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --only-binary=:all: -r \
  https://github.com/OrchardLinux/cli/releases/latest/download/requirements.txt
python -m pip install -r requirements-build.txt
```

Use `orchard-hardware>=0.1.10,<0.2`. To test unpublished packages, install compatible CLI/hardware wheels by their explicit filesystem paths instead of using the hosted requirements. No sibling checkout is required.

## Produce components

- `desktop/build-sources` and `desktop/build`: desktop applications and payload.
- `system/build-rootfs`: signed Arch Linux ARM base and package receipt; see [system/j71b/README.md](system/j71b/README.md).
- Installed hardware producers: kernel, DTB, modules and static BusyBox/Dropbear tools; see [hardware build instructions](https://github.com/OrchardLinux/hardware/blob/main/BUILD.md).
- `python boot/build-loader`: distro-branded loader. Pongo sources and build instructions are under `boot/pongo/`.

Retain each component's receipt. Kernel, modules and DTB must be compatible. Do not change hardware activation or timing as part of presentation changes.

## Assemble

The following example uses component artifacts collected under `out/components/`. Explicit input paths may point anywhere; no source imports from another checkout occur.

```sh
python -m release.j71b.build \
  --release 0.1.0-orchard.3 \
  --base out/components/base/rootfs.tar.gz \
  --base-receipt out/components/base/rootfs.tar.gz.json \
  --modules-dir out/components/kernel/lib/modules \
  --loader out/components/m1n1.bin \
  --kernel out/components/kernel/Image.gz \
  --dtb out/components/kernel/j71b.dtb \
  --pongo out/components/Pongo.bin \
  --busybox out/components/boot/busybox \
  --dropbear out/components/boot/dropbear \
  --dropbearkey out/components/boot/dropbearkey \
  --cursor-tools out/components/desktop/cursor-tools \
  --bluetooth-tools out/components/desktop/bluetooth-tools \
  --labwc-tools out/components/desktop/labwc-tools \
  --output out/releases/0.1.0-orchard.3
```

Choose a new version and output directory for each build. Root builds first; recovery embeds its exact stream receipt, and the index is written last. Installed wheel resources supply hardware code and scripts. `image/j71b/image_policy.py` and `permissions.py` supply desktop readiness, systemd and privilege policy.

## Validate without a device

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
ORCHARD_TEST_DIAGNOSTICS_TOOLS="$PWD/out/components/boot" \
  PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
python -m release.j71b.audit out/releases/0.1.0-orchard.3/j71b-checkm8-pongo.toml
orchard resolve out/releases/0.1.0-orchard.3/index.toml
```

The auditor verifies compressed recovery contents, executable endpoints, integrity lists, root/recovery runtime equality, the embedded root receipt, desktop/privilege policy, loader framing, and absence of private session/firmware data.

Headless finished-artifact checks use Podman without network or device passthrough:

```sh
python -m release.j71b.smoke_desktop \
  --manifest out/releases/0.1.0-orchard.3/j71b-checkm8-pongo.toml \
  --output out/validation/desktop \
  --pointer-helper out/components/validation/wlrctl
python desktop/test-input --artifact-only \
  --manifest out/releases/0.1.0-orchard.3/j71b-checkm8-pongo.toml \
  --output out/validation/input \
  --pointer-helper out/components/validation/wlrctl
```

Choose new evidence directories. `wlrctl` is a test-only native AArch64 helper, not installed in the image; both tests can run without it. They use `localhost/orchard-hardware-kernel-toolchain:bookworm`, built from the hardware package's kernel Containerfile. Native SSH/NSS regression uses the Arch builder image from this repository's base producer.

`tools/with-source-denied --deny PATH [--allow INPUT_DIRECTORY] -- COMMAND...` optionally verifies that a command does not read a source checkout.

## Publish

Follow [Publishing Omarchy A](docs/releasing.md). Build/audit success is not physical-device qualification: test a fresh installation and a cold-restart `orchard launch` on supported hardware before announcing the release. The experimental desktop auto-logs in and grants passwordless sudo; this is disclosed in the README and must not be described as a secure daily-use system.
