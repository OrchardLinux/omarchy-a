import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// One row in a SettingsBox: a glyph, its name and a detail under it, and at
// the end a value, a glyph, a check mark or a switch. It looks as the layout's
// rows do.
Item {
  id: row

  property var settings: null
  property bool first: false
  property string glyph: ""
  property string label: ""
  property string detail: ""
  property string value: ""
  property string trailingGlyph: ""
  property bool checked: false
  property bool isSwitch: false
  property bool switchOn: false
  property bool opens: false
  property bool usable: true
  property bool accent: false

  signal activated()

  width: parent ? parent.width : 0
  height: (settings ? settings.rowHeight : 42) + (detail !== "" ? Style.space(12) : 0)

  readonly property color ink: settings ? settings.text : "white"

  Rectangle {
    visible: !row.first
    width: parent.width; height: 1
    color: Util.alpha(row.ink, 0.07)
  }
  Rectangle {
    anchors.fill: parent
    color: press.pressed ? Util.alpha(row.ink, 0.08) : "transparent"
  }

  Text {
    id: lead
    visible: row.glyph !== ""
    x: Style.space(14)
    width: Style.space(20)
    anchors.verticalCenter: parent.verticalCenter
    text: row.glyph
    color: row.accent ? (row.settings ? row.settings.accent : row.ink) : (row.settings ? row.settings.dim : row.ink)
    font.family: Style.font.menuFamily
    font.pixelSize: Style.font.title
    horizontalAlignment: Text.AlignHCenter
    opacity: row.usable ? 1 : 0.45
  }

  Column {
    x: lead.visible ? lead.x + lead.width + Style.space(12) : Style.space(14)
    width: tail.x - x - Style.space(10)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(1)
    opacity: row.usable ? 1 : 0.45
    Text {
      width: parent.width
      text: row.label
      color: row.accent && row.settings ? row.settings.accent : row.ink
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      elide: Text.ElideRight
    }
    Text {
      visible: row.detail !== ""
      width: parent.width
      text: row.detail
      color: row.settings ? row.settings.faint : "gray"
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }
  }

  Row {
    id: tail
    anchors.right: parent.right
    anchors.rightMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(10)
    opacity: row.usable ? 1 : 0.45
    Text {
      visible: row.value !== ""
      width: Math.min(implicitWidth, row.width * 0.4)
      anchors.verticalCenter: parent.verticalCenter
      text: row.value
      color: row.settings ? row.settings.dim : "gray"
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      elide: Text.ElideRight
    }
    Text {
      visible: row.trailingGlyph !== ""
      anchors.verticalCenter: parent.verticalCenter
      text: row.trailingGlyph
      color: row.settings ? row.settings.dim : "gray"
      font.family: Style.font.menuFamily
      font.pixelSize: Style.font.title
    }
    Text {
      visible: row.checked
      anchors.verticalCenter: parent.verticalCenter
      text: "✓"
      color: row.settings ? row.settings.accent : "white"
      font.family: Style.font.family
      font.pixelSize: Style.font.title
    }
    ToggleSwitch {
      visible: row.isSwitch
      anchors.verticalCenter: parent.verticalCenter
      checked: row.switchOn
      interactive: false
      cursorRing: false
    }
    Text {
      visible: row.opens
      anchors.verticalCenter: parent.verticalCenter
      text: "›"
      color: row.settings ? row.settings.faint : "gray"
      font.family: Style.font.family
      font.pixelSize: Style.font.heading
    }
  }

  TapHandler {
    id: press
    enabled: row.usable
    onTapped: row.activated()
  }
}
