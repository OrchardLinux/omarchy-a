import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// The camera-shutter flash of a screenshot, as on iOS: white over the whole
// screen, fading out. omarchy-capture-screenshot calls it once the shot is
// taken, so the flash is never in the picture.
Item {
  id: root

  property bool opened: false

  function flash() {
    fade.stop()
    white.opacity = 0.9
    opened = true
    fade.start()
  }

  ShellIpc {
    target: "flash"
    function show(): string { root.flash(); return "ok" }
    function ping(): string { return "ok" }
  }

  OverlayWindow {
    id: panel
    shown: root.opened
    shownKeyboardFocus: WlrKeyboardFocus.None
    WlrLayershell.namespace: "omarchy-flash"
    // Visual only: taps go to whatever is below.
    mask: Region {}

    Rectangle {
      id: white
      anchors.fill: parent
      color: "white"
      opacity: 0
    }
  }

  NumberAnimation {
    id: fade
    target: white
    property: "opacity"
    to: 0
    duration: 280
    easing.type: Easing.OutQuad
    onFinished: root.opened = false
  }
}
