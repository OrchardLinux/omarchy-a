# J71b installed system

- `packages.txt`: required signed Arch Linux ARM userspace packages; do not install the generic Arch kernel.
- `build-rootfs`: produce the clean userspace base and package snapshot/receipt.
- `overlay/`: platform gate, charging policy service, framebuffer brightness permissions, kernel-install and initrd configuration.
- `release/j71b/public_root.py`: combine the base, kernel, DTB, modules and device overlay; explicitly set helper executable modes.

The installed system boots directly from its boot entry (kernel, initrd, DTB written by kernel-install); no recovery hands over to it.

The desktop-ready helper runs only in the tablet's Wayland session and captures a compositor frame to `/dev/null`; no screenshot is retained. The device API checks the report's boot ID, live process and socket.
