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

The desktop-ready helper runs only in the tablet's Wayland session and captures a compositor frame to `/dev/null`; no screenshot is retained. The device API checks the report's boot ID, live process and socket.
