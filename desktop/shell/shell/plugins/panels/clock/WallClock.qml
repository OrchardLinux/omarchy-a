import QtQuick
import qs.Commons
import "Model.js" as Model

// Stands in for Quickshell's SystemClock, which schedules its next tick from
// local wall time. In the hour repeated when daylight saving ends, that target
// resolves to the first pass through the hour, so the delay comes out negative,
// QTimer rearms at 1 ms with a warning, and the log floods for the whole hour.
// Epoch milliseconds never repeat, so every delay here stays within one step.
Timer {
  id: root

  // Milliseconds between ticks: 1000 to show seconds, 60000 for minutes.
  property int step: 60000
  property date date: new Date()
  // Epoch milliseconds the armed tick is for.
  property double dueMs: 0

  function arm() {
    var now = Date.now()
    interval = Model.msUntilNextTick(now, step)
    dueMs = now + interval
    restart()
  }

  function tick() {
    date = new Date()
    arm()
  }

  onStepChanged: arm()

  // A new time zone (Settings > Date & Time) shows at once, not at the
  // next tick.
  readonly property int zoneRevision: TimeZone.revision
  onZoneRevisionChanged: tick()
  onTriggered: tick()
  Component.onCompleted: arm()

  // The tick timer runs on monotonic time, which stops while the tablet
  // sleeps: after a wake, or when the system clock is set, the clock would
  // show a stale time for up to a step. Reading the wall clock every two
  // seconds catches both.
  property Timer watch: Timer {
    interval: 2000
    repeat: true
    running: true
    onTriggered: if (Model.tickMissed(Date.now(), root.dueMs, root.step)) root.tick()
  }
}
