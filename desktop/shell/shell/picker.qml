import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "plugins/image-picker"

// Short-lived host for Omarchy's actual ImagePicker component. Qt Quick's
// software renderer cannot draw its MultiEffect masks; only this process uses
// Mesa software OpenGL. The bar, wallpaper and menus stay in the lean shell.
ShellRoot {
  id: host
  property bool wasOpen: false

  ImagePicker {
    id: picker
    onOpenedChanged: {
      if (opened) host.wasOpen = true
      else if (host.wasOpen) exitTimer.start()
    }
  }

  Timer {
    id: exitTimer
    interval: 300
    onTriggered: Qt.quit()
  }

  FileView {
    path: Quickshell.env("OMARCHY_PICKER_REQUEST_FILE")
    onLoaded: picker.open(text())
  }

  ShellIpc {
    target: "picker"
    function ping(): string { return "ok" }
    function open(payload: string): string {
      exitTimer.stop()
      picker.open(payload)
      return "ok"
    }
    function cancel(doneFile: string): string {
      picker.closeSelector(doneFile)
      exitTimer.start()
      return "ok"
    }
  }
}
