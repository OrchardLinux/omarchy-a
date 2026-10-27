# minimal-boot

A kernel, BusyBox and a USB serial root shell, running entirely from RAM.
The content is `init`: read or edit it to change what runs on the iPad.
No build/run wrapper scripts or example registration.

```sh
./orchard build examples/minimal-boot
./orchard run examples/minimal-boot
```

The root launcher selects this checkout's editable CLI automatically. In a VS Code
terminal with the workspace `.venv` activated, bare `orchard` works too.

## What gets built

- `init` becomes `/init`, the device's startup script.
- BusyBox provides the shell and basic utilities.
- Optional `rootfs/` files are copied to matching paths in the RAM filesystem.

To add a program, put an executable at `rootfs/usr/bin/my-tool`. To change startup,
edit `init`. There is no Orchard device agent, RPC protocol, installer, network
service or storage mount. Kernel modules are omitted unless you pass `--modules`;
that stages matching modules but does not activate them.

The CLI handles compilation, caching, packing and uploading directly.

## Host requirements

Install uv, Git and a running native ARM64 Podman environment. The root launcher
initializes missing submodules without resetting existing edits. Local Pongo builds need macOS/Xcode/iPhoneOS SDK; Linux builds
can reuse a local binary with `--pongo FILE`. Booting needs palera1n and libusb.
uv handles editable Python packages without environment activation or releases.

Run only when the intended device is available. This example supports **J71b /
iPad 6 Wi-Fi**. The original charger payload booted on hardware; this extracted
runtime is only offline-tested so far.

## Serial access

After `Boot this device? [Y/n]`, connect to the actual new USB serial port:

```sh
screen /dev/cu.usbmodemYOUR_PORT 115200   # macOS
screen /dev/ttyACM0 115200               # Linux
```

This is **unauthenticated root access over physical USB**. Use a trusted host and
dedicated device. Supplied startup does not install, initialize storage, load
modules or run experiments automatically. Kernel initialization can still affect
hardware. Upload success is not proof of Linux readiness.

## Outputs and reuse

- `~/.cache/orchard/`: shared upstream Git objects and immutable built components.
- `hardware/kernel/.work/j71b/`: checkout-local editable source and incremental output.
- This directory's `out/`: its own boot payload and local receipt.

`XDG_CACHE_HOME` is respected; `ORCHARD_CACHE_DIR` or `--cache DIR` overrides the
cache root. Identical inputs in another checkout reuse the built kernel without
downloading, checking out or compiling Linux again. Local source edits are not
shared between checkouts.

Changing `init` or `rootfs/` only repacks the payload. External-driver and final-DTB
edits reuse the kernel base and its matching module SDK; they do not compile the
upstream kernel. In-tree source/config/patch changes select a new kernel base.
Patch changes still follow the producer's fresh-work-directory requirement.
Do not delete the shared Git object store while editable sources borrow from it.

See [charger-001](../charger-001/) for an example with actual tools in `rootfs/`,
and [CLI build functions](../../cli/docs/ram-development.md) for lower-level use.
