# J71b installed system

- `packages.txt`: required signed Arch Linux ARM userspace packages; do not install the generic Arch kernel.
- `build-rootfs`: produce the clean userspace base and package snapshot/receipt.
- `overlay/`: platform gate, charging policy service, framebuffer brightness permissions and authenticated USB diagnostics.
- `release/j71b/public_root.py`: combine the base, public runtime/modules and device overlay; explicitly set helper executable modes.

The hardware is prepared in recovery. Installed services verify the retained activation/integrity state, then permit the PAM/logind desktop session. Diagnostics start independently so a failed platform gate cannot lock out the installer.

The desktop-ready helper runs only in the tablet's Wayland session and captures a compositor frame to `/dev/null`; no screenshot is retained. The device API checks the report's boot ID, live process and socket.
