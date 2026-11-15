import QtQuick
import qs.Ui

// The last widget of a narrow bar that has more widgets than fit: a press
// turns the bar to the next page of them, and after the last page back to the
// first (Bar.cycleOverflow, BarModel.narrowLayout). The bar adds it by itself;
// it is not meant for shell.json.
BarWidget {
  id: root
  moduleName: "omarchy.overflow"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property bool turned: !!bar && bar.overflowPage > 0

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // Three dots on the first page, a cross to leave the others.
    text: root.turned ? "󰅖" : "󰇘"
    onPressed: function(mouseButton) {
      // Later: the press must not rebuild the section it is delivered in.
      if (mouseButton === Qt.LeftButton && root.bar && typeof root.bar.cycleOverflow === "function")
        Qt.callLater(root.bar.cycleOverflow)
    }
  }
}
