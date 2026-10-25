import QtQuick
import Quickshell
import qs.Ui

BarWidget {
  id: root
  moduleName: "ipadlinux.keyboard"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰌌"
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton && root.bar)
        root.bar.run(Quickshell.env("OMARCHY_PATH") + "/bin/omarchy-keyboard toggle")
    }
  }
}
