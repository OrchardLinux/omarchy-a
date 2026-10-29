# Omarchy A

An experimental, [Omarchy](https://omarchy.org/)-inspired desktop for Apple A-series devices. Built on Arch Linux ARM, with Omarchy's look and feel reworked for touch.

Includes a device-aware CLI and release format for installation, diagnostics, and bringing Omarchy A to more hardware.

## Development checkout

CLI and hardware sources live in the `cli/` and `hardware/` Git submodules.
[uv](https://docs.astral.sh/uv/) manages both as editable local packages; no
virtual-environment activation or published Orchard release is required.

`./orchard` initializes missing source submodules and prepares Python automatically.
Existing submodule checkouts and local edits are never reset or updated. Cloning
with `--recurse-submodules` also works.

For a minimal RAM boot:

```sh
./orchard build examples/minimal-boot
./orchard run examples/minimal-boot
```

The root launcher always uses this checkout's editable CLI and `.venv`, not a
globally installed Orchard or another active environment. Each example contains
its device-side `init` and optional `rootfs/` files; no per-example wrappers,
registration or configuration language. `examples/` is only where we keep samples:
`./orchard build use_cases/my-test` or an unrelated absolute directory works too.

Every payload also gets `/usr/libexec/orchard/usb-session`. When the payload's
`init` runs it, the device has USB serial, USB networking and SSH for this host's
key; the host key is pinned over USB serial on first use:

```sh
./orchard shell                      # root shell
./orchard exec -- dmesg              # one command
./orchard push FILE /tmp/FILE        # copy in, checked by SHA-256
./orchard pull /run/log.txt log.txt  # copy out
```

`push`/`pull --serial` use the USB serial shell instead, for payloads without
SSH (`transport = false` in the example's `orchard.toml`, as in `minimal-boot`).

## Supported devices

| Device | Identifier | Status |
| --- | --- | --- |
| iPad 6 Wi-Fi | `iPad7,5` / J71b | Experimental; no GPU acceleration |

This image uses **tethered boot**: starting Linux after a cold restart requires a host computer running `orchard launch`.

> **Security:** this experimental image automatically logs in as `tablet` and grants unrestricted passwordless sudo. It does not provide local access protection. Use a dedicated test device; do not store sensitive data on it.

Contributions for additional devices are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Install

Use a computer running **Linux or macOS** with Python 3.9+ (including venv/pip), curl, libusb, and OpenSSH installed, a USB data cable, and a supported iPad running iPadOS 16 or later. Allow several GB of free host storage for firmware downloads and extraction.

### 1. Back up your iPad

Storage changes can permanently erase data. Back up before continuing.

### 2. Set up the host tools

```sh
curl -fsSL https://raw.githubusercontent.com/OrchardLinux/omarchy-a/main/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
```

This sets up the [host-side CLI](https://github.com/OrchardLinux/cli) and its dependencies, including palera1n, which is also used by Resize APFS. It only changes the host computer.

On Linux, reconnect the device after setup so USB permissions take effect. Rerun the same bootstrap command to update the CLI; available Omarchy A releases are fetched automatically.

### 3. Make room for Linux

Skip this step if you already have a suitable Linux-data partition on your device.

1. Download and extract [Resize APFS](https://github.com/OrchardLinux/resize-apfs/releases/latest).
2. Run `./resize-apfs boot` from its extracted folder and follow the prompts.
3. Once iPadOS starts, unlock the iPad and open **Resize APFS** when its icon appears.
4. Choose **Adjust size**, reserve space for Linux, and select the option to create an **unformatted Linux partition**.
5. Wait for **Completed and verified** before restarting. Do not interrupt the operation; see the [resize safety instructions](https://github.com/OrchardLinux/resize-apfs#while-resizing) if status becomes unavailable.

### 4. Install Omarchy A

Connect only the target iPad. Enter DFU: hold Home + Power for about 8 seconds, release Power, then keep holding Home for about 10 seconds. The screen should remain black.

```sh
orchard install omarchy-a
```

Follow the prompts to select the partition and confirm installation. The CLI downloads and verifies the release, boots recovery, prepares device-specific firmware, installs the desktop, and hands off to the installed system—all in one DFU boot. Keep USB connected until **System ready**.

## Start Linux after a restart

Connect the iPad in DFU mode and run:

```sh
orchard launch
```

Select a compatible installation and confirm launch. This downloads shared boot assets, not a root image, and does not format or reinstall anything. It requires the hardware release's published launcher assets. If the verified host firmware cache is missing, use `orchard launch --allow-firmware-download` to permit downloading the required inputs. See the [CLI launch instructions](https://github.com/OrchardLinux/cli#launch-an-installed-system).

## More than an installer

The same CLI supports hardware work before and after installation:

```sh
orchard devices       # Inspect connected devices
orchard status        # Query the running system
orchard diagnostics   # Collect device diagnostics
```

Recovery boot, device-tree capture, firmware preparation, installation, and handoff are available separately for bring-up and debugging. See the [CLI documentation](https://github.com/OrchardLinux/cli#documentation) for commands and workflows.

## How it works

An iPad cannot boot a Linux installer like a PC boots an ISO. [How Omarchy A gets from DFU to desktop](docs/how-it-works.md) explains the boot path, release format, device runtime, and installation lifecycle.

## Contribute or bring up a device

- **Desktop:** improve touch interaction, the shell, applications, and Omarchy integration here.
- **Hardware:** contribute kernel patches, device trees, firmware recipes, and runtime support to [hardware](https://github.com/OrchardLinux/hardware).
- **Host tooling:** improve device adapters, boot transports, and installation workflows in [CLI](https://github.com/OrchardLinux/cli).
- **Create your own remix:** customize the desktop, root filesystem, and image policy using the same release format; [minimal-linux](https://github.com/OrchardLinux/minimal-linux) provides a smaller, Alpine-based example.

See [CONTRIBUTING.md](CONTRIBUTING.md) for bring-up guidance and [BUILD.md](BUILD.md) for image assembly and validation.

## Troubleshooting

See [Troubleshooting](docs/troubleshooting.md) for USB connectivity, diagnostics, and failed installations.
