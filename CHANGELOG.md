# Changelog

Notable changes to Omarchy A: what someone using the tablet or installing it
would notice. Kernel, driver, device and installer changes come from orchard;
each release names the orchard release it is built on, and
[orchard's changelog](https://github.com/OrchardLinux/orchard/blob/main/CHANGELOG.md)
covers them.

Add an entry under **Unreleased** in the same pull request as the change. When
releasing, rename that section to the version (`## [0.3.0] - YYYY-MM-DD`). The
release workflow uses that section as the GitHub release notes and fails if it
is missing or empty.

## [Unreleased]

### Highlights

The screen rotates with the iPad, and landscape no longer lags. Volume keys
work, with an on-screen display.

### Desktop

- Fix the System menu’s Shutdown and Reboot actions.
- Automatic rotation on the iPad 6 through iio-sensor-proxy, using orchard's
  in-kernel accelerometer driver; rotation waits for the device to settle, and
  touch follows the panel. Based on Dalton Alexandre's rotation work.
- Landscape without lag: wlroots ships as a patched package.
- Volume starts quiet; the volume keys step in 5% steps and show the shell's
  on-screen display; the mixer is in the bar.
- No leftover boot splash between the greeter and the desktop.
- Power locks and darkens the screen at once; the iPad sleeps 10 s later. One
  press wakes it, in well under a second, and Home wakes it too.
- Plugging in lights the screen.
- The greeter and the lock screen go dark after 30 s without input, the desktop
  after 5 minutes.

### Build

- Package downloads survive a stalling mirror: bounded download attempts move
  on to the next mirror and keep what was already downloaded.

## [0.2.0] - 2026-10-31

Built on orchard 0.2.0.

### Highlights

One image for every device: the root carries no board or kernel of its own,
and orchard supplies the kernel, devicetrees and initrd for each platform. It
installs with the release's own installer, and the desktop gained a greeter, a
PIN sign-in and a files app.

### Install

- Install with the release's `install.sh`; the installer asks for the account
  password and a PIN and imports this computer's SSH key.
- The installed system offers SSH and a USB serial login as normal system
  services.
- The root is compressed with zstd, which makes the download smaller.

### Desktop

- Greeter with sign-in by PIN at boot, at the desktop's scale, without a
  cursor.
- Tablet power policy; the lock screen keeps a dark panel dark on taps and
  volume keys, and so do the brightness keys with the screen off. (Dalton
  Alexandre)
- Dolphin as the files app, and upstream Omarchy themes.
- The top bar can be hidden and shown, the menu's toggles work, Maximize
  Windows is a toggle that survives updates, and Bluetooth keyboards get
  keyboard shortcuts. (Dalton Alexandre)
- Boot splash while the system starts.
- The panel backlight is found on every device, not only the iPad 6.
  (Berkay Kösebay)

### System

- pacman works on a fresh install, `iw` is installed, compressed RAM swap
  through zram, and a static hostname. (Dalton Alexandre)
- The battery gauge is polled every 10 seconds. (Berkay Kösebay)
- sudo asks for the account password; the system names itself Omarchy.
- The `hardware-check` example tests any device, with a quick Wi-Fi mode at
  boot.

### Contributors

Dalton Alexandre and Berkay Kösebay.
