import QtQuick
import qs.Ui

BarWidget {
  id: root
  moduleName: "omarchy.menu"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\ue900"
    fontFamily: "omarchy"
    onPressed: function(button) {
      if (!root.bar) return
      if (button === Qt.RightButton) root.bar.run("foot")
      // Orchard: the logo opens the launcher, the dependable path on a phone
      // without a Home button; Settings in it opens the menu.
      else root.bar.run("omarchy-shell omarchy.dock apps")
    }
  }
}
