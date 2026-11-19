import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

BarWidget {
  id: root
  moduleName: "ipadlinux.keyboard"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // Lit while the keyboard is up, as omarchy-keyboard records it.
  FileView {
    id: keyboardState
    path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/omarchy-keyboard-visible"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰌌"
    active: keyboardState.loaded && keyboardState.text().trim() === "1"
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton && root.bar)
        root.bar.run(Quickshell.env("OMARCHY_PATH") + "/bin/omarchy-keyboard toggle")
    }
  }
}
