# Omarchy A

An experimental, [Omarchy](https://omarchy.org/)-inspired desktop for Apple A-series devices. Built on Arch Linux ARM, with Omarchy's look and feel reworked for touch.

Includes a device-aware CLI and release format for installation, diagnostics, and bringing Omarchy A to more hardware.

## Development checkout

This repository is the distribution: desktop, root filesystem and release. The
hardware support and the `orchard` tool live in
[orchard](https://github.com/OrchardLinux/orchard); put its launcher on your PATH
once (see its [README](https://github.com/OrchardLinux/orchard#develop)). Here,
`orchard` runs orchard's `main` by default. To work against your own orchard
checkout, e.g. a branch with a driver you need, name it in `orchard.local.toml`,
which is never committed:

```toml
orchard = "../orchard-installer"
device = "j71b"
```

`distro.toml` makes this checkout an orchard distribution:

```sh
orchard build        # every component that changed, then a release in out/releases/dev-DATE-TIME
orchard run          # build, then start that release's recovery on the attached iPad, from RAM
orchard install      # install the last build
orchard python -m unittest discover -s tests
```

`orchard build` runs `tools/build.py`, which keeps each component (desktop,
Labwc, base, loader, …) in `out/components/` and rebuilds it only when its files
change; orchard brings Pongo, the recovery tools and the kernels.
[BUILD.md](BUILD.md) describes the steps one by one.

RAM experiments and device bring-up happen in orchard itself, with its
[examples](https://github.com/OrchardLinux/orchard/tree/main/examples) and
[bring-up guide](https://github.com/OrchardLinux/orchard/blob/main/docs/device-bring-up.md).

## Supported devices

A release covers every device orchard describes: one root image, and
orchard's kernel, device trees and modules for each platform. How well a device
works is orchard's device data, which the installer shows before it changes
anything. Today the iPad 6 Wi-Fi (`iPad7,5`, J71b) is supported, without GPU
acceleration; the others are experimental. See orchard's
[devices](https://github.com/OrchardLinux/orchard/tree/main/devices).

This image uses **tethered boot**: starting Linux after a cold restart requires a host computer running `orchard launch`.

> **Security:** this experimental image logs in as `tablet` automatically at boot. `sudo` asks for the password chosen at install, and the screen lock takes a 6-digit PIN. There is no disk encryption, and the boot ROM exploit used to start Linux gives anyone holding the device full access. Use a dedicated test device; do not store sensitive data on it.

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

The installer needs at least 9 GiB that iPadOS doesn't use: free space, or an earlier Linux install to replace. It never resizes iPadOS itself. Skip this step if you already have that.

1. Download and extract [Resize APFS](https://github.com/OrchardLinux/resize-apfs/releases/latest).
2. Run `./resize-apfs boot` from its extracted folder and follow the prompts.
3. Once iPadOS starts, unlock the iPad and open **Resize APFS** when its icon appears.
4. Choose **Adjust size** and reserve space for Linux.
5. Wait for **Completed and verified** before restarting. Do not interrupt the operation; see the [resize safety instructions](https://github.com/OrchardLinux/resize-apfs#while-resizing) if status becomes unavailable.

### 4. Install Omarchy A

Connect only the target iPad. Enter DFU: hold Home + Power for about 8 seconds, release Power, then keep holding Home for about 10 seconds. The screen should remain black.

```sh
orchard install omarchy-a
```

Choose where Omarchy A goes, then set a password (for `sudo` and system changes) and a 6-digit PIN (for the lock screen). The CLI downloads and verifies the release, boots recovery, writes a boot partition and the system next to iPadOS, adds the device's firmware, and starts Omarchy A, all in one DFU boot. Keep USB connected until it says Omarchy A is starting.

### Coming from the previous installer

Installs from the previous installer (one Linux partition, no boot partition) can't be started or converted by this one. The installer offers that partition as a target and says so before erasing it. To keep files, copy them off first: start the old system with the previous CLI release, then copy them over the network (for example with `scp`).

## Start Linux after a restart

Connect the iPad in DFU mode and run:

```sh
orchard launch
```

The bootloader reads the boot entries from the iPad's boot partition and starts the one you choose (or the only one). It works from any computer with Orchard installed: nothing is downloaded, formatted or reinstalled. See the [CLI launch instructions](https://github.com/OrchardLinux/cli#launch-an-installed-system).

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
- **Hardware and host tooling:** contribute kernel patches, device trees, firmware recipes, runtime support, device adapters, boot transports and installation workflows to [orchard](https://github.com/OrchardLinux/orchard).
- **Create your own remix:** customize the desktop, root filesystem, and image policy using the same release format; [minimal-linux](https://github.com/OrchardLinux/minimal-linux) provides a smaller, Alpine-based example.

See [CONTRIBUTING.md](CONTRIBUTING.md) for bring-up guidance and [BUILD.md](BUILD.md) for image assembly and validation.

## Troubleshooting

See [Troubleshooting](docs/troubleshooting.md) for USB connectivity, diagnostics, and failed installations.
