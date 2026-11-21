import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons

// This device as the system reports it: model, system, version, kernel,
// memory and storage. Nothing here is typed in; a line the system cannot
// answer is left out.
Item {
  id: page

  property var settings: null
  // Read by Settings as its window opens (Settings.qml), so the table is
  // whole when the page comes in instead of growing under the finger; read
  // again here, as storage changes.
  readonly property var facts: settings && settings.host ? settings.host.aboutFacts : []
  Component.onCompleted: if (settings && settings.host) settings.host.readAbout()
  readonly property bool ready: facts.length > 0

  width: parent ? parent.width : 0
  height: box.height

  Rectangle {
    id: box
    width: page.width
    height: factColumn.height + 2
    color: settings ? settings.fill : "transparent"
    border.width: 1
    border.color: settings ? settings.line : "gray"
    Column {
      id: factColumn
      x: 1; y: 1
      width: parent.width - 2
      Repeater {
        model: page.facts
        Item {
          required property var modelData
          required property int index
          width: factColumn.width
          height: settings ? settings.rowHeight : 40
          Rectangle {
            visible: parent.index > 0
            width: parent.width; height: 1
            color: Util.alpha(settings ? settings.text : "white", 0.07)
          }
          Text {
            x: Style.space(14)
            anchors.verticalCenter: parent.verticalCenter
            text: parent.modelData.label
            color: settings ? settings.text : "white"
            font.family: Style.font.family
            font.pixelSize: Style.font.subtitle
          }
          Text {
            anchors.right: parent.right
            anchors.rightMargin: Style.space(14)
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, parent.width * 0.6)
            horizontalAlignment: Text.AlignRight
            text: parent.modelData.value
            color: settings ? settings.dim : "gray"
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
          }
        }
      }
    }
  }
}
