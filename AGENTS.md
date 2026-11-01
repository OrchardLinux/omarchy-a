# Notes for coding agents

Building, running and device rules are orchard's; see orchard's
[AGENTS.md](https://github.com/OrchardLinux/orchard/blob/main/AGENTS.md).

## Changelog

- CHANGELOG.md is curated: one entry per meaningful unit of work that someone
  using the tablet would notice (desktop, system or install behaviour), not
  per commit, refactor or CI change. Kernel, driver and device changes belong
  in orchard's changelog.
- When you finish such a unit, propose the entry under Unreleased: what
  changed, described by its effect. Add it only after the user explicitly
  approves it, and never edit the changelog without that approval.
