import QtQuick
import Quickshell
import qs.Ui
import qs.Commons

// The control center's button: one click opens it as a popup, as the bar's
// other icons open theirs (a finger pulls it down from the top right). The bar's other icons stay
// upstream's, each opening its own panel.
BarWidget {
  id: root
  moduleName: "ipadlinux.controlcenter"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property var center: root.bar && root.bar.shell ? root.bar.shell.controlCenter : null

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰘮"
    tooltipText: I18n.t("controlCenter.title")
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton && root.center) root.center.togglePopup()
    }
  }
}
