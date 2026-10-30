# J71b automatic rotation

`apple-aop.service` runs once per boot as root. Orchard's private firmware
mixin installs `apple/j71b-aop.osbin` from the cached J71b IPSW; no Apple
firmware is distributed here. `firmware.py` validates the container and
segments, passes RAM-only images to the C daemon and never writes patched
firmware to disk. The daemon uses the hardware repo's DT-backed DMA owner
and boot ECID handoff. There are no `/dev/mem` or diagnostic probe modes.

The core's firmware cannot safely restart after stopping. The kernel
halts it before releasing DMA, retains buffers if halt fails and prevents
another start until a system reboot. The system unit deliberately has
`Restart=no`. A missing firmware file or identity handoff skips the unit.

The daemon consumes the advertised AFK rings and atomically publishes
`/run/apple-aop/orientation` with a one-second heartbeat. The labwc session
imports its actual `WAYLAND_DISPLAY` and `LABWC_PID`, then starts the user
controller. Codes 2/3/1/4 mean Home bottom/left/top/right respectively and
map to normal/90/180/270 transforms. Flat or unknown poses retain the
current orientation; stale or malformed state cannot trigger a rotation.

The controller debounces for 400 ms, identifies one enabled native iPad
panel and changes only its transform. It composes the matching touch
matrix onto the user's baseline calibration, preserves unrelated labwc
configuration and rolls back if applying display or input changes fails.
The original `rc.xml` is saved as `rc.xml.before-aop-rotation`. A per-unit
`base_matrix` in `~/.config/apple-aop/rotation.json` takes precedence over
that saved calibration; the shipped config contains no per-unit values.
Start from a portrait calibration when first enabling the controller.
Main's touch driver is named `iPad7,5 Touchscreen`. Migrating a private
prototype config also requires updating its old `J71b Z2 Touchscreen
(experimental)` category while retaining that device's calibration values.

Create `~/.config/apple-aop/rotation.lock` to hold orientation while
calibrating; remove it to resume. The controller reapplies the current
pose after unlocking. The nine-target calibration tools and captured
measurements remain bring-up tools outside this PR.

`animate_rotation` defaults to false. The software snapshot animation
stuttered or barely animated on the current framebuffer renderer, so the
experimental overlay is not shipped and setting this flag true reports
an error. Direct rotation remains available.

## Local checks

```sh
python -m unittest discover -s tests -v
python desktop/build-aop --output out/apple-aop-daemon
python desktop/build-aop --test --output out/aop-protocol-test
```

The last check builds a static AArch64 executable with synthetic AFK
records and uses `qemu-aarch64-static` on other host architectures. It
does not open any device. The normal desktop build includes the daemon
and stages the launcher, units, controller and default config into its
hashed payload; the J71b root builder enables the system service.

The earlier installed prototype worked in all four poses. This packaged
version adds DT ownership, a kernel start ioctl, firmware validation and
boot identity handoff; it has not been booted on a device. A hardware
integration build must precede the distro release that uses it. The
submodule pin alone does not update CI's published hardware wheel and
component inputs: select a release containing these changes when
assembling an image.
