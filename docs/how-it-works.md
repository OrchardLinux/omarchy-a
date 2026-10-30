# How Omarchy A gets from DFU to desktop

Omarchy A needs to distribute more than a desktop filesystem. It must also provide a way to boot Linux on a locked Apple device, prepare its hardware, and install the system safely. This document explains that path and the interfaces that keep it reusable as device support grows.

The boot sequence below describes the current iPad 6 Wi-Fi (J71b) implementation.

## Why not ship an ISO?

On a conventional PC, firmware can start a distribution's installer from removable media. The installer can discover storage, install the system, and arrange subsequent boots through a supported boot mechanism. The ISO contains the bootable installation environment.

An Apple A-series device does not offer that ordinary PC boot path. For the current port, several problems must be solved before an installer can access a usable Linux system:

- **Boot access:** Apple's boot chain does not normally accept an unsigned Linux image. The current port enters through the checkm8 BootROM exploit.
- **Platform support:** Linux needs a compatible kernel, device tree, drivers, firmware, and device-specific hardware initialization.
- **Storage:** iPadOS occupies an APFS container. Making room requires resizing it using Apple's APFS facilities, not an ordinary Linux partitioning screen.
- **Device-specific data:** some firmware preparation requires calibration and configuration captured from the actual device.

Omarchy A therefore packages both the system to install and the components needed to boot its installation environment.

## The workaround: boot a temporary Linux system first

A host computer starts a Linux recovery environment in the device's RAM. Recovery contains the tools needed to prepare hardware and install Omarchy A onto internal storage.

For J71b, the boot chain is:

```text
Host computer
  └─ palera1n / checkm8
       └─ PongoOS
            └─ m1n1
                 └─ Linux kernel + recovery initramfs
```

PongoOS receives the recovery payload over USB. The payload combines m1n1, boot arguments, a device tree, the Linux kernel, and a compressed initramfs. m1n1 starts Linux, which unpacks and runs the recovery userspace in RAM.

Recovery is a small Linux system containing USB connectivity, SSH, storage tools and kernel modules. It brings up internal storage read-only at boot and never writes to it by itself.

The installer writes two partitions next to iPadOS: a boot partition and the Omarchy A root. Every later start goes through the same chain, but m1n1 loads the kernel, initrd and device tree from the boot partition instead of recovery from the host (see the [boot contract](https://github.com/OrchardLinux/orchard/blob/main/docs/boot-contract.md)).

## What a release contains

A release combines the public artifacts for a particular device and boot method:

| Artifact | Purpose |
| --- | --- |
| `index.toml` | Maps supported devices and boot methods to installation manifests. |
| Device installation manifest | Identifies the release, compatibility requirements and required artifacts with their sizes and SHA-256 hashes. |
| `pongo.bin` | Early boot environment used by the current checkm8/Pongo path. |
| `recovery.bin` | RAM-bootable payload containing the loader, device tree, kernel, and recovery userspace. |
| `rootfs.tar.zst` | The persistent Omarchy A filesystem: Arch userspace, desktop, applications, configuration, its kernel, device tree and modules. |

The rootfs carries its own kernel the way a normal Arch system does: `/usr/lib/modules/<version>/vmlinuz` plus the board's DTB, set up for `kernel-install` with mkinitcpio.

Local manifests can reference files beside them. Hosted releases use explicit HTTPS artifact URLs. The CLI handles acquisition and verification in either case. Hashes establish consistency with the selected metadata, not publisher authenticity on their own.

## The code on each side of USB

| Host CLI | Recovery |
| --- | --- |
| Detect and confirm the device | Publish the live device and boot identity |
| Resolve, download, and verify release artifacts | Bring up storage read-only at boot |
| Perform the USB boot transport | Authorize the host's SSH key over USB serial |
| Acquire Apple firmware and prepare the private bundle | Run the host's install script as root |
| Choose the target, ask for the password and PIN | |
| Run the install script over SSH and show its progress | |

The recovery's own command, `orchard-device`, has two operations: `bootstrap` (over USB serial) and `status`. Everything else is the CLI's install script, which the CLI copies to the device for each install, so the host and the device side always come from the same version.

## Installation lifecycle

### 1. Make room

On the device, [Resize APFS](https://github.com/OrchardLinux/resize-apfs) shrinks the iPadOS container to free space. The tethered installer never resizes APFS; it uses free space, or replaces an earlier Linux partition after you type out the confirmation.

### 2. Boot recovery and connect

The CLI identifies the connected device, resolves its release and starts recovery through palera1n and PongoOS. Recovery exposes USB serial and USB networking. The CLI provisions an SSH key through the serial connection, pins the host key recovery returns, and connects.

### 3. Plan

The install script reads the partition table (`inspect`). The CLI offers the possible targets, asks for the system password and the 6-digit lock-screen PIN, and computes a plan: which partitions to create or replace, and where. Nothing has been written yet.

### 4. Install

The CLI uploads the plan, the private firmware bundle and the secrets (root-only, in RAM), then streams the rootfs into `install_device.py run`. The script:

- checks the partition table still matches the plan, then creates the partitions;
- formats the boot partition (FAT32) and the root (ext4);
- extracts the rootfs while checking its SHA-256, and adds the firmware;
- sets the password and the PIN, then deletes the secrets;
- runs `kernel-install` in the new system, which writes the kernel, initrd, DTB and boot entry to the boot partition.

It never touches APFS or any partition the plan doesn't name. Progress comes back as JSON events.

### 5. Start Omarchy A

Put the device in DFU mode and run `orchard launch`. m1n1 reads the boot entries from the boot partition, loads the chosen kernel, initrd and device tree, and starts Omarchy A. Boot is tethered: every cold start goes through `orchard launch`.

## Why these boundaries matter

- **New hardware does not require a new user workflow.** A port supplies its kernel, device tree, firmware recipe and device description; the recovery and the install script are the same for every device.
- **Desktop changes do not belong in the boot transport.** Omarchy A can evolve its shell, applications, and system policy without touching USB upload or storage safety logic.
- **The installed system is an ordinary Arch system.** Its kernel updates go through `kernel-install` like on any Linux machine with a boot partition.
- **Private inputs remain separate from public releases.** The same published artifacts can be used while preparing the device-specific firmware locally.

The minimal Alpine-based [example image](https://github.com/OrchardLinux/minimal-linux) exercises the same boundaries without Omarchy A's desktop or systemd policy.

## Failures

The install script checks the partition table against the plan before its first write and refuses a stale plan. If an install stops partway, run `orchard install` again: it inspects the disk afresh and offers the partitions the interrupted run created as replace targets. The script's log is `/run/orchard/install.log` on the recovery until it reboots.

## Implementation references

- [Release assembly](../release/j71b/build.py) and [manifest generation](../release/manifests.py).
- [Image assembly and validation instructions](../BUILD.md).
- [Host orchestration](https://github.com/OrchardLinux/orchard/blob/main/src/orchard/service.py) and the [install script](https://github.com/OrchardLinux/orchard/blob/main/src/orchard/install_device.py).
- [Recovery runtime](https://github.com/OrchardLinux/orchard/tree/main/runtime/recovery), [recovery image producer](https://github.com/OrchardLinux/orchard/tree/main/src/orchard/image) and the [boot contract](https://github.com/OrchardLinux/orchard/blob/main/docs/boot-contract.md).
