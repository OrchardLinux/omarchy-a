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

## Unreleased

### Desktop

- At boot the splash stays on screen until the PIN screen is ready, then fades
  into it, instead of going black for a few seconds first.

## [0.3.3] - 2026-11-24

Built on orchard 0.3.3.

### Desktop

- On the GPU desktop, the shell and Qt apps draw without depth and stencil
  buffers, as iOS draws its interface. On the iPod touch 6 the shell uses
  about 50 MB less memory, and every Qt app about 18 MB less.
- On the GPU desktop, the shell no longer stays invisible on a device whose
  screen is driven by simpledrm. Labwc used to try to show it straight from
  the GPU's buffer, which simpledrm cannot take, and now composites it there.
  A display driver that takes the GPU's buffers keeps showing them directly.
- Every iPad, iPhone and iPod touch screen now starts at the size it has
  under iOS. Before, only the iPad 6, iPad 7 and iPhone 7 did; on the others,
  such as the iPod touch 6, everything was drawn at half size.
- On a phone held upright, the on-screen keyboard has ten keys across as on
  iOS, under a short row of Esc, Tab, Ctrl, Alt and the arrows. 123 holds the
  digits and common symbols, and #+= the rest, plus Home, End, Page Up/Down
  and Delete.
- A new launcher replaces the app grid: Home, Super and the bar's logo open
  apps, actions and (on a phone) the system controls in swipeable tabs, with
  search, recent apps and files, long-press app menus and full keyboard
  control.
- The lock and login screen have a new look: a large clock over the
  wallpaper, six PIN slots and the shell's own keypad, and a wrong PIN shown
  in red without anything moving.
- After a new install, the first lock screen stays lit for ten minutes
  instead of going dark after 30 seconds; later locks dim as before.
- Before the screen locks after five idle minutes, it dims to half brightness
  only for the last ten seconds, instead of to 10 % for the last two
  minutes, and any touch brings the brightness back.
- The Home button responds to every press: it no longer depends on what the
  keyboard is doing.
- No more separate login screen: the tablet boots straight to the lock, the
  same screen as after Power, and the desktop is ready the moment you enter
  the PIN. Logout starts a fresh desktop behind the lock.
- The lock screen shows the status icons in its corner: Wi-Fi, battery, and
  Bluetooth, a muted microphone, rotation lock and Stay Awake when they're on.
- The lock screen's keypad is cleaner: digits only, without key backgrounds.
- A control center: pull down from the top right, click its icon or press
  Super+Ctrl+1 for Wi-Fi, Bluetooth, brightness, volume and quick toggles.
  Long-press for the full settings pages.
- The status bar is back to Omarchy's compact size. Stay Awake sits with the
  icons on the right, and the keyboard button is gone: swipe up from the
  bottom, or use the control center.
- The launcher opens with a gentle zoom on the theme's plain background; the
  blurred wallpaper is a choice in Trigger > Toggle.
- On a phone, About and Omacalc open full screen like every other window.
- A touch no longer leaves hover highlights, tooltips or close marks behind,
  in the shell and in apps.
- Notifications appear as banners at the top of the screen: one at a time,
  with a reply field where the app offers one, or stacked (Trigger > Toggle >
  Stack Notifications). Swipe a banner away, or tap it to open the app.
- The control center opens over the on-screen keyboard and leaves it open.
- A notification center: pull down from the top left or click the clock to
  see the weather and all recent notifications, grouped by app. Tap one to
  open it, reply where the app offers it, swipe it away, or clear them all.
  A swipe up from the bottom puts it, or the control center, away.
- The control center's Focus tile switches Do Not Disturb, as the
  notification center does.
- Settings, as an app: Wi-Fi, Bluetooth, display, sound, appearance with
  themes, backgrounds and icon sets to pick from, behaviour, keyboard,
  privacy, apps, updates and this device's details, searchable, in the
  launcher and in Exposé like any app (`omarchy-settings` opens any page).
- Much more of the Omarchy menu works on the tablet: fonts, language,
  default apps, kernels, installing and removing software, security
  setup and more. Docker's entries show once Docker is installed.
- Focus shows as a bell in the status bar and on the lock screen while on.
- Maximized windows have no title bar, as on a tablet; Settings >
  Behaviour brings them back. Floating windows keep theirs.
- The control center's pages slide in smoothly: Wi-Fi no longer pauses
  halfway while it looks for networks.
- The notification center slides down from the top when the clock is
  clicked, as when it is pulled.
- About shows an icon on its renderer line, as on every other.
- The control center and the notification center can be used fully from
  the keyboard (Super+Ctrl+1 and Super+Ctrl+2).
- Settings has Date & Time: the time zone, automatic time and a 24-hour
  switch for every clock.
- Settings lists every keyboard shortcut (Settings > Keyboard).
- The bar's background and clock format can be changed in Settings, and
  rows that do nothing on this device are dimmed.

## [0.3.2] - 2026-11-19

Built on orchard 0.3.2.

### Desktop

- Updates without reinstalling: Omarchy A's desktop and system settings are
  now a package, so `omarchy-update` (or Update > Omarchy) brings each release
  to an installed tablet; your own settings stay yours.
- Desktop follows upstream Omarchy's latest: app icons drawn in your theme's
  colors (Papercraft, Arcade or the apps' own, under Appearance > Icons), a
  Display panel showing the screen's resolution and density with a text size
  slider, and the captive-portal Sign in button and Learn links open Firefox.
- On-screen keyboard: it opens when you tap a text field and closes when you
  tap outside, in every app. It steps aside while you type on a physical
  keyboard.
- Windows open maximized.
- The Power and Home keys of physical keyboards work like the iPad's.
- If going to sleep fails, the iPad retries later instead of staying awake in
  the dark.
- GNOME Web starts on the GPU desktop, and Omactivity's panel no longer slides
  across the screen at start.

## [0.3.1] - 2026-11-15

Built on orchard 0.3.1.

### Desktop

- Mesa, Labwc, wlroots, Omactivity and Files come from the Orchard package
  repository and update with `pacman -Syu`.
- Files replaces Dolphin on ARMv7.
- At large display scales the bar keeps every icon behind a "…" button, and
  panels scroll.
- Holding a key on the on-screen keyboard repeats it.
- The lock screen rotates with the same crossfade as the desktop.
- The built-in microphone is listed as "Internal Microphone".

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
