# Notes for coding agents

Building, running and device rules are orchard's; see orchard's
[AGENTS.md](https://github.com/OrchardLinux/orchard/blob/main/AGENTS.md).

## Everything benefits every device

**Every change benefits every device it can.** A desktop, audio, power or
input change applies to every board that has the hardware, not only the one
you tested on. Key it on what the device has (a driver, a sensor, a property
it reports), not on a board name.

**Every opt-in or opt-out needs a very good reason, written next to it:** the
hardware is absent, or there is evidence that it breaks that board.
**"Untested" is never a reason.**

## Changelog

- CHANGELOG.md is curated: one entry per meaningful unit of work that someone
  using the tablet would notice (desktop, system or install behaviour), not
  per commit, refactor or CI change. Kernel, driver and device changes belong
  in orchard's changelog.
- When you finish such a unit, propose the entry under Unreleased: what
  changed, described by its effect. Add it only after the user explicitly
  approves it, and never edit the changelog without that approval.

## Installed tablets

- Everything this repository puts on a tablet is the `omarchy-a` package
  (`release/package.py`; the recipe is OrchardLinux/packages' `packages/omarchy-a/arch`).
  Tablets get it with a release, through `[orchard]`, and `pacman -Syu` /
  `omarchy-update`. A changed file the package ships reaches them by itself.
- The tablet user's files (`~/.config`, seeded from `/etc/skel`) are theirs:
  a changed default reaches only new users. When existing ones need it, add a
  migration (`desktop/shell/bin/omarchy-dev-add-migration`, user-level, no
  sudo; replace a whole file with `omarchy-refresh-config`, which keeps a
  backup). Root's part of a change goes into
  `system/overlay/usr/lib/omarchy-a/package-install`.
- A new runtime dependency goes into the recipe's `depends` in
  OrchardLinux/packages, not `system/packages.txt`.
