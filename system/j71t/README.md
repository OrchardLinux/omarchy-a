# J71t installed system

iPad 5 Wi-Fi (`iPad6,11`, J71t/S8003). See [docs/devices.md](../../docs/devices.md) for what works.

- `packages.txt`: required signed Arch Linux ARM userspace packages; do not install the generic Arch kernel.
- `build-rootfs`: the J71b userspace recipe with this package list.
- `overlay/`: platform gate, framebuffer brightness permissions, USB diagnostics networking and the tablet network rule.
- `release/j71b/public_root.py --device j71t`: combine the base, public runtime/modules, the J71b layer's device-independent session files (`release/devices.py`) and this overlay.

The hardware is prepared in recovery. `j71t-platform-ready.service` runs the hardware runtime's read-only `j71t-check-platform` before the desktop session starts; diagnostics start independently.

Unlike J71b there is no charging service: the J71t charger policy runs in the kernel. Suspend stays disabled, as on J71b. The panel backlight is `20e200000.backlight` (the J71t kernel maps the whole DWI block); the power-key screen toggle selects it automatically.

The tablet layer of the separate omarchy-ipad5 Hyprland image is deliberately not included: its gestures and on-screen keyboard are Hyprland-specific (Omarchy A has its own labwc keyboard), and auto-rotation needs the AOP accelerometer driver, which this port does not ship.
