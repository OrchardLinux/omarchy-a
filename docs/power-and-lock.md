# Power, lock and sleep: the state model

`omarchy-powerd` (`system/overlay/usr/libexec/omarchy-powerd`) is the one owner
of the screen, the lock request and sleep. Its state machine, the `Machine`
class, has no I/O and no clocks; `tests/test_powerd.py` walks every reachable
state with every input and checks the invariants below. Whether a board may
suspend at all is not decided here or by device data: every board may (see
orchard `docs/bring-up/suspend.md`); this model decides when.

## Requirements

1. Power, released after a short press on its own, requests lock and eases the
   backlight to dark over 240 ms. Home and Power pressed together on a lit
   screen take a screenshot (`omarchy-capture-screenshot fullscreen`) when the
   first of them comes up within 1.5 s; Home then does not open the dock
   (`omarchy-home-button` asks `omarchy-powerctl home`). Held longer (the DFU
   and restart combination), they do nothing. Sleep follows
   only after the screen stayed dark for a short while. Idle
   screen-off has an eight-second grace period before requesting lock.
2. **The first press always wakes.** No press is lost or replayed.
3. **Press to lit well under 1 s** (target ≤ 0.5 s), measured and logged per wake.
4. Every input has one defined effect in every state, and a press causes exactly
   one transition.
5. Home is not Power: Home never darkens or sleeps.
6. Any suspend, whatever started it, is preceded by lock and dark.
7. Playback keeps playing: dark and running instead of asleep, volume keys
   working.
8. A board without suspend behaves the same, minus sleep.
9. Being plugged in lights the screen, as on any tablet, asleep or awake. Being
   unplugged wakes the kernel (orchard) but stays dark and sleeps again.

## One owner

A system service, because it serves the greeter and the desktop alike, and
because system services thaw with the kernel while `user.slice` stays frozen a
little longer. No user-space code runs before the kernel's device resume
finishes, so that time is the floor for press to lit: a driver that blocks its
resume (`apple_z2`, ~3.4 s in round 5) has to be fixed in the driver. Kernel log
times inside resume cannot measure this (printk showed 133 ms for what ktime
measured as 3.36 s); the key timestamps can. It:

- reads the `gpio-keys` input device itself (Power, Home), with kernel
  timestamps on `CLOCK_MONOTONIC`. No process per press. labwc no longer binds
  Power; labwc's Home binding is only the session's home action and does not
  fire while locked. A Home press that woke a dark screen (in the grace before
  the lock, when the session is still unlocked) opens nothing either:
  `omarchy-powerctl home` answers `wake`. Volume stays with labwc, `allowWhenLocked`, and never
  touches the panel or the state;
- reads every input device that reports `SW_MACHINE_COVER` (the iPad
  Smart Cover; the kernel names two hall sensors, each its own device). The
  cover is closed while any sensor says so: closing it is a `lock`, opening
  it a `wake`. The kernel wakes the iPad from sleep when the cover opens;
  the sensors are polled and report the opening right after resume;
- owns the backlight: brightness 0 is dark. The display pipeline stays on, so
  lighting it again needs no modeset and shows the lock screen it last showed;
- remembers the last lit level in `/var/lib/omarchy-powerd/brightness` each
  time the screen goes dark and at shutdown, and restores it once per boot (half
  brightness if nothing is remembered, never below 5%). `systemd-backlight` is
  disabled: it would save the dark 0 and start every later boot at its minimum;
- asks the session's shell to lock (as the session's user: `omarchy-shell lock
  lock`, then `status` until `secure`). The greeter has nothing to lock;
- requests sleep through logind, and holds a logind delay inhibitor so that a
  suspend from anywhere else comes through here first (`PrepareForSleep`);
- takes the session's inputs over `/run/omarchy-powerd.sock` (group `video`):
  `/usr/libexec/omarchy-powerctl idle` (the idle timeouts), `wake`,
  `input` (lit or dark, for lock-screen taps), `status`. Upstream's
  `omarchy-system-lock` and `omarchy-system-wake` send `idle` and `wake`.

No state is inferred from brightness or files. After a restart the state is
`ON` and the panel is lit: it fails towards a visible, locked-or-not screen.

## States and their invariants

| State | Panel | System | Invariants |
|---|---|---|---|
| `ON` | lit or fading in | running | `inflight` may still be true right after a wake. |
| `GRACE` | fading out, then dark | running | Idle only; no lock or suspend requested until the eight-second grace expires. |
| `SETTLING` | dark | running | Lock requested; settle timer armed or expired. Nothing suspended yet. |
| `DARK` | dark | running | Dark and awake with no timer, **only** for playback, a block inhibitor, or a board that cannot suspend. |
| `SUSPENDING` | dark | entering, asleep, or leaving sleep | Entered only from `SETTLING` with the lock confirmed, or from a logind signal. `inflight` is true. |

**Can screen-off and sleep conflict? No.** Every non-`ON` state targets dark;
backlight animation is visual state, not authorization to sleep. A pending
fade-to-dark is completed before any suspend/inhibitor release. The only way
to request sleep is
`SETTLING` → `SUSPENDING`, which requires dark and a confirmed lock. The panel
is lit only by the transition to `ON`. The tests assert this for every reachable
state: panel dark exactly when state ≠ `ON`, and `suspend` only ever dark and
locked. A sleep can still be finishing behind a lit screen for a moment (`ON`
with `inflight`), because the press lights the panel without waiting for it.

**A dark screen never silently means running indefinitely.** Power enters
`SETTLING` immediately. Idle first enters `GRACE`, then `SETTLING` if no input
arrives within eight seconds. Only the reasons listed for `DARK` hold it there. A
suspend that did not happen is tried again after the settle time.

`ASLEEP` is not a state of the daemon: frozen, it cannot be in one. It is the
part of `SUSPENDING` it does not run in; the log tells them apart (below).

## Inputs

| Input | Source |
|---|---|
| `power`, `home` | gpio-keys, with the kernel timestamp: Home and a Power on a dark screen on key **down**; Power on a lit screen on key **up** after a short lone press. Home + Power is not a machine event: it runs the screenshot in the session |
| `idle` | shell: idle timeout, or the lock screen's blank timeout |
| `dim`, `undim` | shell: 3 minutes idle on a touch session dims the panel to 10 % while lit; input restores it unless the brightness was changed meanwhile. Not machine events: the state stays `ON` |
| `brightness PANEL LEVEL EXPECTED`, `als-state` | automatic brightness (`docs/tablet-sensors.md`): a write is accepted only while lit, not dimmed or fading, and only if the panel still holds `EXPECTED`, so a manual change or a dark screen stops it |
| `lock` | the menu's Lock (`omarchy-system-lock`): lock at once, no grace; closing the Smart Cover |
| `wake` | lock screen: input while lit; opening the Smart Cover |
| `settle` | settle timer |
| `grace-ended` | eight-second idle grace timer |
| `lock-ok`, `lock-failed` | the shell's answer to the lock request |
| `playing`, `not-playing` | playback check, once a second while dark |
| `sleep-signal` | logind `PrepareForSleep(true)`, someone else's suspend |
| `sleep-ended` | `systemd-suspend.service` finished, or `PrepareForSleep(false)` |
| `suspend-refused` | `CanSuspend` is not yes: this board cannot sleep |
| `suspend-blocked` | a block inhibitor appeared just before asking |
| `suspend-busy` | a wakeup event was in progress at the `wakeup_count` handshake, or the request failed |
| `timeout` | the suspend never happened (30 s of running time) |

**Playing** means: logind reports a **block** inhibitor for `sleep`
(`BlockInhibited`; also what a package update or a test takes), or PipeWire
(`pw-dump`, as the session's user) has a `Stream/Output/*` node in state
`running`. Test without audio: `systemd-inhibit --what=sleep sleep 60`.

During `GRACE`, activity (`omarchy-powerctl input`) wakes without requesting a
lock. After grace expires, dark-screen taps are ignored (`input` answers
`dark`). Volume works in every state without lighting anything and does not
restart the settle timer. Explicit locking is never undone by grace.

## Transitions

| From | Input | To | Actions |
|---|---|---|---|
| `ON` | `power`, `lock` | `SETTLING` | dark; lock; arm settle |
| `ON` | `idle` | `GRACE` | dark; arm grace |
| `GRACE` | `power`, `home`, `wake` | `ON` | cancel grace; light; no lock request |
| `GRACE` | `grace-ended`, `lock` | `SETTLING` | lock; arm settle |
| `GRACE` | `sleep-signal` | `SUSPENDING` | cancel grace; lock; finish dark fade before releasing inhibitor |
| `ON` | `home`, `wake` | `ON` | nothing (the session's Home does its home action) |
| `ON` | `sleep-signal` | `SUSPENDING` | dark; lock; let logind go once locked |
| `SETTLING` | `power`, `home`, `wake` | `ON` | cancel settle; light; tell the lock screen |
| `SETTLING` | `settle` | `SUSPENDING` | ask for sleep, if the lock is confirmed; else on `lock-ok` |
| `SETTLING` | `lock-failed` | `ON` | light; notify: never an unsecured desktop that looks locked |
| `SETTLING` | `playing` | `DARK` | cancel settle |
| `DARK` | `power`, `home`, `wake` | `ON` | light; tell the lock screen |
| `DARK` | `not-playing` | `SETTLING` | arm settle (not on a board that cannot suspend) |
| `DARK` | `lock-failed` | `ON` | light; notify |
| `SUSPENDING` | `power`, `home`, `wake` | `ON` | light at once; the sleep ends or aborts by itself |
| `SUSPENDING` | `sleep-ended` | `SETTLING` | stay dark, arm settle: no button woke it (charger, alarm, abort) |
| `SUSPENDING` | `suspend-refused` | `DARK` | until a press |
| `SUSPENDING` | `suspend-blocked` | `DARK` | as playing; `not-playing` settles again |
| `SUSPENDING` | `suspend-busy` | `SETTLING` | try again after the settle time |
| `SUSPENDING` | `timeout` | `SETTLING` | try again after the settle time |

Every other pair does nothing. Three rules make presses exact:

- **A press is never lost.** Just before asking for sleep the daemon does the
  kernel's `wakeup_count` handshake. From then on any key press makes the kernel
  abort the sleep or end it, at whatever stage, so a press while entering sleep
  cannot leave the tablet asleep.
- **Keys are read before anything else** in each turn of the loop, so a wake
  press is seen before the end of the sleep and decides that a button woke it.
- **Presses from before the panel lit belong to that wake.** They queue while
  tasks are frozen, and the kernel timestamp tells them apart: consumed and logged.
  A press after it lit is a new command, even while the sleep is still finishing
  (the next sleep then waits for it).

**A sleep ends when `systemd-suspend` ends, not when a kernel attempt does.** A
wakeup event just before the kernel starts (`power_supply_changed` counts as one)
makes that attempt fail; systemd-sleep then tries again, and the kernel no longer
checks. The daemon re-arms the handshake when it sees the failure, which narrows
the gap but cannot fully close it: a press in those few milliseconds needs a
second press. `suspend_stats` give only the log's `result=slept|aborted`.

Rapid presses on an awake tablet simply toggle: `ON` ↔ `SETTLING`, each one
instant, and sleep only follows 10 s after the last one left it dark.

## Values

| | Value | Why |
|---|---|---|
| Idle lock grace | 8 s | Quick wake does not require a new PIN; explicit lock is unchanged |
| Screen fade | 240 ms | Smoothstep easing, reversible immediately; event loop never sleeps for animation |
| Settle (lock requested → sleep) | 10 s | After Power immediately, or after the idle grace expires |
| Desktop idle → dark | 5 min | the shell's `idle.lock` |
| Lock screen idle → dark | 30 s | the lock's blank timer, sent as `idle` |
| Greeter idle → dark | 30 s | `IdleMonitor` in the greeter's `shell.qml` |
| Playback check | 1 s, only while dark | `SETTLING` is longer, so it is seen first |
| Suspend timeout | 30 s of running time | counted in loop ticks |

`CLOCK_MONOTONIC` stops in a sleep, and so do kernel and journal times; the log's
`seconds=` comes from `CLOCK_BOOTTIME`. Key timestamps and the time the panel lit
are both taken after the clock runs again, so `press_to_lit_ms` holds.

If logind starts again it may have forgotten the delay inhibitor, so the daemon
takes a new one when it sees logind take its name. The end of a sleep does not
depend on logind: it is the end of `systemd-suspend`.

Later: long press for a power menu. Until then a long press is a press.

## Reading a run from the journal

`journalctl -u omarchy-powerd -o short-monotonic`. Every transition, with the
event's own time (the kernel's for keys):

```
t=245.310114 power: SUSPENDING -> ON cancel-suspend light woke
wake from=ASLEEP-or-entering press=245.310114 lit=245.318402 press_to_lit_ms=8.3
sleep-ended result=slept seconds=46.012 wakeup_irq=78
```

`wake from=SETTLING` (or `DARK`) means it never slept: instant by design.
`from=ASLEEP-or-entering` followed by `result=slept` was a real sleep of that
length; `result=aborted` means the press came while it was entering sleep.
`press_to_lit_ms` runs from the wake press, so it includes the kernel's resume,
and ends at the start of the brightness transition. Full target brightness is
reached over 240 ms; the loop continues to service wake inputs throughout.
What the panel shows is the last frame; the lock screen's own update follows
when `user.slice` thaws.

## What this replaced

`omarchy-tablet-power` (one process per press, state in brightness and files, a
fixed window after resume), `omarchy-screen-toggle` and `omarchy-greeter-wake`
(a second and third writer of the backlight).
