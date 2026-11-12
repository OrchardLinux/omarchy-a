import QtQuick

// Hyprland leaves an already-mapped layer surface at its old global position
// when its monitor moves within the layout: undocking disables the internal
// panel, the external monitor shifts to x=0, and long-lived surfaces such as
// the bar and background keep rendering at the old offset — or entirely
// off-screen — until they are unmapped and remapped. Watch the screen's
// origin and pulse `remapping` when it moves; the owning window folds that
// into its `visible` binding so the compositor re-places the surface at the
// monitor's new origin.
Item {
  id: root

  required property var window
  readonly property var screen: window ? window.screen : null

  // Fold into the window's binding: visible: <shown> && !guard.remapping
  property bool remapping: false
  property var lastPosition: null

  function rememberPosition() {
    lastPosition = screen ? Qt.point(screen.x, screen.y) : null
  }

  function checkPosition() {
    if (!screen) { lastPosition = null; return }
    var next = Qt.point(screen.x, screen.y)
    // Qt may emit xChanged/yChanged for a size-only geometry change. A
    // rotation at the same origin must never hide the bar or wallpaper.
    if (lastPosition === null) { lastPosition = next; return }
    if (next.x === lastPosition.x && next.y === lastPosition.y) return
    lastPosition = next
    settleTimer.restart()
  }

  onScreenChanged: rememberPosition()
  Component.onCompleted: rememberPosition()

  visible: false

  // A layout reshuffle can move the monitor more than once before it lands.
  // Let the positions settle before the single remap pulse.
  Timer {
    id: settleTimer
    interval: 200
    onTriggered: root.remapping = true
  }

  // Hold the surface unmapped for a beat so the compositor processes the
  // unmap before the remap instead of coalescing them into a no-op.
  Timer {
    interval: 50
    running: root.remapping
    onTriggered: root.remapping = false
  }

  Connections {
    target: root.screen
    function onXChanged() { root.checkPosition() }
    function onYChanged() { root.checkPosition() }
  }
}
