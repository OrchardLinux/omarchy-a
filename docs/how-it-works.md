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

Recovery is a small Linux system containing USB connectivity, SSH, storage tools, kernel modules, and the device runtime.

After installation, recovery switches into the installed filesystem without rebooting the kernel. Hardware prepared during recovery remains initialized. This is how the installation can proceed from DFU to the desktop in one Linux boot.

## What a release contains

A release combines the public artifacts for a particular device and boot method:

| Artifact | Purpose |
| --- | --- |
| `index.toml` | Maps supported devices and boot methods to installation manifests. |
| Device installation manifest | Identifies the release, compatibility requirements, default installation directory, and required artifacts with their sizes and SHA-256 hashes. |
| `pongo.bin` | Early boot environment used by the current checkm8/Pongo path. |
| `recovery.bin` | RAM-bootable payload containing the loader, device tree, kernel, and recovery userspace. |
| `rootfs.tar.zst` | The persistent Omarchy A filesystem: Arch userspace, desktop, applications, configuration, kernel modules, runtime, and services. |

The installer extracts the rootfs archive into a directory on a Linux-data partition, normally `/omarchy`.

The builder produces the rootfs first. Its exact compressed size, digest, and extraction limits are then embedded in recovery. Recovery uses these values to accept only the matching rootfs. Recovery and the rootfs also receive matching public runtime files and kernel modules. The release index is written after the artifacts and manifest are ready.

Local manifests can reference files beside them. Hosted releases use explicit HTTPS artifact URLs. The CLI handles acquisition and verification in either case. Hashes establish consistency with the selected metadata, not publisher authenticity on their own.

## The code on each side of USB

The installation has two cooperating sides:

| Host CLI | Device runtime |
| --- | --- |
| Detect and confirm the device | Verify the live device and boot identity |
| Resolve, download, and verify release artifacts | Validate incoming payloads against recovery's embedded requirements |
| Perform the USB boot transport | Initialize hardware using the device's supported sequence |
| Acquire Apple firmware and prepare private inputs | Inspect and fence storage; validate targets and destinations |
| Present selection and confirmation prompts | Format, extract, finalize, and commit the installation |
| Stream payloads and display progress | Switch root and report readiness, errors, and diagnostics |

The **device runtime** consists of the device-side programs and supporting scripts included in both recovery and the installed rootfs. Its command endpoint is `orchard-device`.

This boundary keeps storage paths, module loading, mount operations, and hardware timing on the device. The CLI requests operations rather than reproducing those procedures as remote shell commands.

Omarchy A supplies the installed-system policy: which init to start, how to validate the rootfs and privileges, and what counts as a ready desktop. Hardware support supplies the platform implementation. These policies are included at image-build time.

## Installation lifecycle

### 1. Prepare storage separately

[Resize APFS](https://github.com/OrchardLinux/resize-apfs) runs under iPadOS, uses Apple's APFS facilities to resize its container, and can create an unformatted Linux partition.

This happens before Linux installation and is not part of the single DFU-to-desktop boot. The Linux installer can format an eligible existing Linux-data partition after confirmation; it does not shrink APFS or create that partition.

### 2. Resolve the release and boot recovery

The CLI identifies the connected device, selects its release manifest and supported boot method, and obtains the verified images. For a device in DFU, it invokes palera1n to start PongoOS, uploads the recovery image, and waits for Linux USB connectivity.

If matching, unused recovery is already running, the CLI can use it directly.

### 3. Establish authenticated communication

Recovery exposes USB serial and USB networking. The CLI creates an SSH key and provisions its public key through the physical serial connection. Recovery returns its SSH host key and network endpoint; the CLI pins that identity before connecting.

Subsequent requests invoke a command over SSH:

```text
orchard-device OPERATION BASE64_JSON
```

Requests carry a protocol version. Responses are newline-delimited JSON events describing phases, progress, results, or errors. Firmware and rootfs payloads travel on stdin while events return on stdout.

Credentials are scoped to the selected device and boot.

### 4. Prepare firmware and hardware

The host obtains pinned Apple firmware inputs and captures a fresh Apple Device Tree (ADT) from recovery. It uses these to prepare a private, data-only firmware archive, called a **mixin**.

The runtime verifies the archive's allowlist, hashes, and binding to the live ADT before writing firmware into RAM. It then performs the device-specific hardware preparation. For J71b, this includes Wi-Fi, fenced storage access, touch, Bluetooth, and charging policy.

The runtime and modules come from the public release; device-specific firmware data arrives separately in the mixin.

### 5. Select a destination and install

The runtime reports eligible partitions and their identities. The host presents the choices and obtains explicit approval for formatting or replacement. The runtime rechecks the selected destination, available capacity, and identity before modifying it.

The host streams the compressed rootfs to the runtime, which decompresses and extracts it into a fresh staging directory without storing another compressed copy on the device. It checks the stream against recovery's embedded receipt, validates the extracted system and privileges, and copies the prepared private firmware into the installed filesystem.

Only a validated installation is promoted to its final directory and given a completion receipt. Replacement permanently deletes the approved existing destination without a backup.

### 6. Hand off to the desktop

The CLI requests handoff. The runtime validates the completed installation and signals recovery's PID 1, which mounts the installed root, preserves the required runtime filesystems, and uses `switch_root` to start Omarchy A's systemd.

```text
Recovery userspace in RAM
          │
          │ same kernel and initialized hardware
          ▼
Installed Omarchy A userspace on storage
```

The installed diagnostic service can reuse this boot's SSH credentials independently of desktop startup. The CLI polls status until Omarchy A's readiness checks confirm a live desktop session, then records success and asks whether to retain diagnostic SSH. The default is to revoke it for this boot.

## Why these boundaries matter

- **New hardware does not require a new user workflow.** A port supplies its hardware implementation and host adapter behind the same operations. Kernel, device-tree, firmware, and early-boot work are still required.
- **Desktop changes do not belong in the boot transport.** Omarchy A can evolve its shell, applications, and system policy without rewriting USB upload or storage safety logic.
- **The release carries its installation environment.** Users do not manually match a kernel, recovery filesystem, modules, and desktop archive; the build binds them together.
- **Private inputs remain separate from public releases.** The same published artifacts can be used while preparing the required device-specific data locally.
- **Bring-up remains inspectable.** Recovery boot, firmware preparation, installation, handoff, status, and diagnostics are accessible separately rather than hidden inside an indivisible installation script.

The minimal Alpine-based [example image](https://github.com/OrchardLinux/minimal-linux) exercises the same boundaries without requiring Omarchy A's desktop or systemd policy. It demonstrates that these interfaces separate image policy from hardware mechanics; the initial device implementation remains J71b-specific.

## Reboots and failures

The installed rootfs and private firmware persist on storage. Hardware activation and diagnostic credentials are boot-time state. Boot is tethered: after a cold restart, use `orchard launch` from a host with the device in DFU mode. Shared recovery discovers compatible completed installations and starts the selected root after confirmation, without downloading another root image or reinstalling. The low-level `boot` command starts recovery only.

A disconnected or timed-out mutation has an uncertain outcome, not permission to retry. The runtime tracks attempted phases, retains diagnostic evidence, and limits cleanup to recognized incomplete staging. A failed attempt can require a fresh recovery boot. A readiness timeout after root installation is not, on its own, a reason to reinstall.

## Implementation references

- [Release assembly](../release/j71b/build.py) and [manifest generation](../release/manifests.py).
- [Image assembly and validation instructions](../BUILD.md).
- [Host orchestration](https://github.com/OrchardLinux/cli/blob/main/src/orchard_cli/service.py).
- [Device operation protocol](https://github.com/OrchardLinux/cli/blob/main/docs/device-protocol.md), [host adapter contract](https://github.com/OrchardLinux/cli/blob/main/docs/adapter-contract.md), and [SSH lifecycle](https://github.com/OrchardLinux/cli/blob/main/docs/ssh-lifecycle.md).
- [Device runtime](https://github.com/OrchardLinux/hardware/tree/main/runtime/j71b) and [recovery image producer](https://github.com/OrchardLinux/hardware/tree/main/image).
