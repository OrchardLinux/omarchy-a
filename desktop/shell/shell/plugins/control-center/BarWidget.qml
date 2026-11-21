import QtQuick
import Quickshell
import qs.Ui
import qs.Commons

// The control center's button: one click opens it as a popup, as the bar's
// other icons open theirs (a finger pulls it down from the top right). The bar's other icons stay
// upstream's, each opening its own panel.
// Not on the default bar (a finger pulls the center down, the keyboard has
// Super+Ctrl+1); a user can still add "ipadlinux.controlcenter" to their layout.
BarWidget {
  id: root
  moduleName: "ipadlinux.controlcenter"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property var center: root.bar && root.bar.shell ? root.bar.shell.controlCenter : null

  // Open as a popup, it is the bar's open popup like any other: the bar
  // draws its mark under this button, and another item's popup opening (or
  // the bar's switching between them) closes it through close().
  readonly property bool popupShown: !!root.center && root.center.opened && root.center.popupStyle
  onPopupShownChanged: {
    if (!root.bar) return
    if (root.popupShown) root.bar.requestPopout(root)
    else root.bar.releasePopout(root)
  }
  function open() { if (root.center && !root.center.opened) root.center.togglePopup() }
  function close() { if (root.center && root.center.opened) root.center.close() }
  function closeForPopoutSwitch() { root.close() }

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
