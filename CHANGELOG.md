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

## [0.3.0] - 2026-11-12

### Highlights

Full GPU acceleration on the iPad 6 and 7: the desktop and apps run on the
GPU, and Firefox plays YouTube with hardware video. A proper tablet experience,
with an app switcher that shows every open window, Omactivity for what's
running, and Files with a touch mode. Installing takes under two minutes
instead of four. More supported devices, the screen rotates with the iPad, and
login and the lock screen flow smoothly.

### Desktop

- On the iPad 6 and 7 the desktop and apps run on the GPU, and Firefox plays
  YouTube with hardware video decoding.
- Files: Omarchy's file manager, now with a touch mode, replaces Dolphin on
  64-bit boards.
- Qt apps (Files, Omactivity, Omacalc) draw on the GPU on the GPU desktop.
- App switcher: four fingers up, Home pressed twice or Super+Tab show every
  open window side by side, minimised ones included. Tap one to bring it back,
  flick it up to close it.
- The iPad 7 panel gets scale 2 at login in both orientations. The scale script only matched the iPad 6 modes, so 1620×2160 stayed at scale 1.
- A five-row on-screen keyboard with punctuation on the main layer, double-tap
  Shift for Caps Lock, immediate key highlight, and a slide in and out.
- Swipe up from the bottom edge to open the keyboard.
- Rotation lock in the Display menu; rotation no longer makes the bar and
  wallpaper flicker, crossfades, and a quick half turn rotates once.
- Idle screen-off waits eight seconds before locking, so a quick wake needs no
  PIN; screen off and on fade.
- Stay Awake in the Display menu, with an icon in the bar while it is on.
- Login and logout go from one picture to the next without a black screen.
- Fix the System menu’s Shutdown and Reboot actions.
- Automatic rotation on the iPad 6 through iio-sensor-proxy, using orchard's
  in-kernel accelerometer driver; rotation waits for the device to settle, and
  touch follows the panel. Based on Dalton Alexandre's rotation work.
- Landscape without lag: wlroots ships as a patched package.
- Volume starts quiet; the volume keys step in 5% steps and show the shell's
  on-screen display; the mixer is in the bar.
- No leftover boot splash between the greeter and the desktop.
- Power locks and darkens the screen when released; held, alone or with Home
  (DFU, restart), it does nothing. The iPad sleeps 10 s later. One press wakes
  it, in well under a second, and Home wakes it too.
- Home and Power together take a screenshot, with a flash; it goes to
  ~/Pictures/Screenshots.
- Omactivity, a touch task manager: in the menu and with Super+Shift+T.
- A long press on a saved Wi-Fi network offers Forget and Change passphrase.
- Wi-Fi connects to 5 GHz networks right after a boot.
- The speakers are called "Speakers"; tapping a bar icon no longer flashes the
  Stay Awake mug; the first boot starts at full brightness.
- Omacalc comes from Omarchy's package repository and updates with the system.
- The installer shows Omarchy's mark at the size it boots with.
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
