# Following upstream Omarchy

Omarchy A is upstream Omarchy's desktop running on labwc instead of Hyprland,
on a touchscreen. It follows one upstream commit, written in
`desktop/upstream.lock` (and `desktop/shell/UPSTREAM_COMMIT`), and the
OrchardLinux/packages recipe fetches the same commit. Moving to a newer upstream
means moving both pins together.

## What comes from upstream, and how

- **At build time, unchanged:** `themes/` (Jade Horse is the tablet's first
  theme and the greeter's fallback) and `applications/foot.desktop`, taken from
  the pinned tarball by `desktop/install-tree`.
- **Copied into this repository:** `desktop/shell/` holds upstream's whole
  `shell/` tree and the parts of `bin/`, `default/` and `config/` the tablet
  uses, at the same paths as upstream. Most files are upstream's unchanged; the
  rest are listed below.

## Files that differ from upstream

Every change carries a comment at the place it differs (`// Orchard:`,
`# Labwc port`, or a comment that says what the tablet needs). In short:

**Ported to labwc, upstream's name and arguments, own implementation.**
`bin/omarchy` (only `version`, `update`, `migrate`, `hook install`),
`omarchy-theme-set` (theme switch backend), `omarchy-launch-about`,
`omarchy-capture-screenshot` (grim), `omarchy-brightness-display`,
`omarchy-monitor-state`, `omarchy-hyprland-monitor-scaling` and `-persist`
(wlr-randr),
`omarchy-hyprland-window-close-all` and `omarchy-launch-or-focus` (the shell
over wlr-foreign-toplevel), `omarchy-system` (logout ends labwc),
`omarchy-system-lock` and `-wake` (omarchy-powerd owns the screen),
`omarchy-battery-status` (measured iPad battery data), the update chain
(`omarchy-update`, `-confirm`, `-restart`, `-system-pkgs`, `omarchy-migrate`:
one pacman upgrade of the omarchy-a package, no snapshots, AUR, mise or boot
verification), `omarchy-launch-floating-terminal-with-presentation` (foot, no
gum), `omarchy-dev-add-migration`, `omarchy-toggle-bar`,
`omarchy-toggle-enabled`, `omarchy-menu-images`, `omarchy-bluetooth-device`,
`omarchy-launch-browser` and `omarchy-launch-webapp` (Firefox; upstream's web
apps need Chromium).

**Changed for touch and the tablet in the shell.**
The Display panel is upstream's with three more rows (auto-brightness,
rotation lock, Stay Awake); its commands run on labwc (`omarchy-monitor-state`
reads wlr-randr, `omarchy-brightness-display` takes upstream's `--monitor`),
the iPad's `Unknown-1` connector counts as the built-in display, and the
rotate menu stays shut (the screen turns with the iPad), as do the resolution
and refresh rows (no labwc command; an iPad's panel has one mode). Upstream's text size
slider ships unchanged. The Power panel is upstream's reading the iPad's
battery as it is: charging from the battery's own state, the charger from
sysfs, no rotating phrases, scrolling on short screens. Smaller
changes: the bar (narrow-bar pages, a hidden bar unmaps because labwc never
brings back a parked layer surface, no drag-reorder by finger, and its surface
is only the strip: upstream spans the screen so Hyprland cannot pull a dragged
pointer off the bar, which costs a full-screen layer on every frame), indicators
(no hover reveal on touch), the lock (6-digit PIN pad, a 30 s lit lock, wake
only by Home and Power), the idle service (omarchy-powerd's idle), the keyboard
panel, menu and overlays (below the on-screen keyboard), the app grid (a text
field for the on-screen keyboard), network rows (long press for Forget and
Change passphrase), Bluetooth pairing feedback, the background (no Hyprland
boot cover or theme intro videos, software decode at panel size), the greeter's data-only theme
snapshot (`Commons/Color.qml`) and wallpaper readiness (`LockView.qml`),
`Style.qml` (a larger bar target), `config/omarchy/shell.json` (the tablet's bar
and the plugins it turns off).

**Menu.** `default/omarchy/omarchy-menu.jsonc`: Reboot says it leaves Linux,
Activity opens Omactivity, Setup > Monitors opens the Display panel, Maximize
Windows toggles, the Agent section shows only once the agent commands are
installed. `desktop/install-tree` also points Suspend at the kernel's
charger PM readiness.

**Translations.** `default/i18n/en/cli.json` holds only the keys of the commands
shipped here; `shell.json` adds the auto-brightness and captive-portal keys.

**Our own files** (no upstream counterpart): the labwc config, theme renderer
and window buttons (`labwc-*`, `render-labwc-*.py`), the on-screen keyboard
(`bin/omarchy-keyboard`, `shell/plugins/keyboard/`), the bar's Overflow widget,
the screen flash, the Home button and overview, rotation lock, auto-brightness,
volume keys, the background picker process, Bluetooth pairing window,
`uwsm-app` (apps in their own systemd scope), KDE colours, greeter theme
publishing, fastfetch/starship/foot/fontconfig defaults, the pinned Tokyo Night
palette in `theme/` and our migrations.

## Moving the pin

1. Take the old pin (base), our `desktop/shell/` (ours) and the new upstream
   (theirs) as three trees. For every file of ours that exists upstream:
   unchanged from base → take theirs; changed → `git merge-file ours base theirs`
   and resolve by hand. Files we rewrote outright (see above) stay ours; read
   upstream's diff for fixes worth porting. Copy files upstream added to
   `shell/`; drop the ones it deleted.
2. Find commands the new files call that the tablet lacks
   (`omarchy-*` in `shell/`, `bin/`, the menu). Add an upstream command
   unchanged when it is small and has no Hyprland dependency, port it under its
   upstream name when the tablet needs it, or leave it out when only a hidden or
   Hyprland-only path calls it.
3. Check `omarchy-i18n` keys of shipped commands against `cli.json`.
4. Bump `desktop/upstream.lock`, `desktop/shell/UPSTREAM_COMMIT` and the
   recipe's `_omarchy` and checksum in OrchardLinux/packages together.
5. Run the tests, then boot the tablet: login, bar and every panel, lock and
   wake, theme switch, the menu, the app grid, rotation, the on-screen keyboard.
