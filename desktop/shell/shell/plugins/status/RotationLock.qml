import QtQuick
import Quickshell
import Quickshell.Io

// Whether rotation is locked: omarchy-rotation-lock's file, which only exists
// while it is. Read every two seconds, as a missing file cannot be watched.
Item {
  id: root
  visible: false
  property bool locked: false

  FileView {
    id: file
    path: (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")) + "/omarchy/rotation-lock"
    printErrors: false
    onLoaded: root.locked = true
    onLoadFailed: root.locked = false
  }
  Timer {
    interval: 2000
    running: true
    repeat: true
    onTriggered: file.reload()
  }
}
