import QtQuick
import qs.Commons
import qs.Commons as Commons

// A group on a Settings page of its own (Wi-Fi, Bluetooth, Sound): a caption
// and its rows in one box, a line between them, as the layout's groups look.
Column {
  id: box

  property var settings: null
  property string title: ""
  default property alias rows: inner.data

  spacing: Style.space(6)

  Text {
    visible: box.title !== ""
    text: box.title.toUpperCase()
    color: box.settings ? box.settings.faint : "gray"
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    font.letterSpacing: 1.5
    leftPadding: Style.space(2)
  }
  Rectangle {
    width: parent.width
    height: inner.height + 2
    color: box.settings ? box.settings.fill : "transparent"
    border.width: 1
    border.color: box.settings ? box.settings.line : "gray"
    Column {
      id: inner
      x: 1; y: 1
      width: parent.width - 2
    }
  }
}
