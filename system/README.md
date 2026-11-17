# Installed system

One root image for every platform. orchard's platform layer (kernel, DTBs,
modules and orchard's hardware defaults under `/usr/lib`) goes next to it at
install time. This directory is Omarchy A's policy only.

- `packages.txt`: the base the image adds to the `omarchy-a` package (recipe: OrchardLinux/packages `packages/omarchy-a/arch`), whose dependencies are the desktop; never a kernel package.
- `build-rootfs`, `assemble-rootfs`: produce the clean userspace base and its package snapshot and receipt, installing the `omarchy-a` package of the same checkout from a repository of the build's own. The platform's packages (Mesa, wlroots, Labwc, the video bridge, Omafox, Omactivity, Files) come from the Orchard package repository, listed first in the image's `/etc/pacman.conf`; see [BUILD.md](../BUILD.md#packages).
- `overlay/`: power and sleep policy, sudo and polkit rules, backlight permissions, Bluetooth and screen helpers. Part of the `omarchy-a` package, so updated with it; a file another package owns goes to `/usr/share/omarchy/etc-overrides` and the package's hook puts it in place.
- `release/public_root.py`: add what only an image has to the base (orchard's SSH and DHCP tools, the boot splash, the release's name, the services a first boot starts).

A file under `/etc` overrides orchard's default of the same name under `/usr/lib`.

The installed system boots directly from its boot entry, which orchard's installer writes with orchard's kernel, initrd and the board's DTB; no recovery hands over to it, and the system needs no kernel-install or initrd generator.

The ready helper runs in the greeter's and the tablet's Wayland sessions once their shells are up. The greeter's record, `/run/omarchy-greeter/ready.json` (directory from tmpfiles.d), tells the installer the PIN screen is on; it holds the boot ID, the shell's process and its socket.
