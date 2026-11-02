# Installed system

One root image for every platform. orchard's platform layer (kernel, DTBs,
modules and orchard's hardware defaults under `/usr/lib`) goes next to it at
install time. This directory is Omarchy A's policy only.

- `packages.txt`: required signed Arch Linux ARM userspace packages; never a kernel package.
- `build-rootfs`, `assemble-rootfs`: produce the clean userspace base and its package snapshot and receipt.
- `overlay/`: power and sleep policy, sudo and polkit rules, backlight permissions, Bluetooth and screen helpers.
- `release/public_root.py`: combine the base, desktop and overlay; explicitly set helper executable modes.

A file under `/etc` overrides orchard's default of the same name under `/usr/lib`.

The installed system boots directly from its boot entry, which orchard's installer writes with orchard's kernel, initrd and the board's DTB; no recovery hands over to it, and the system needs no kernel-install or initrd generator.

The ready helper runs in the greeter's and the tablet's Wayland sessions once their shells are up. The greeter's record, `/run/omarchy-greeter/ready.json` (directory from tmpfiles.d), tells the installer the PIN screen is on; it holds the boot ID, the shell's process and its socket.
