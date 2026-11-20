import QtQuick
import qs.Commons
import qs.Commons as Commons

// A level in a SettingsBox row: a glyph (a tap on it is the glyph's, e.g. a
// mute), then a track the finger or the pointer sets anywhere along.
Item {
  id: slider

  property var settings: null
  property bool first: false
  property string glyph: ""
  property real level: 0          // 0..1
  property bool usable: true
  property bool dimmed: false     // muted: shown, but fainter

  signal moved(real value)
  signal glyphTapped()

  width: parent ? parent.width : 0
  height: settings ? settings.rowHeight + Style.space(6) : 48

  readonly property color ink: settings ? settings.text : "white"

  Rectangle {
    visible: !slider.first
    width: parent.width; height: 1
    color: Util.alpha(slider.ink, 0.07)
  }
  Text {
    id: lead
    x: Style.space(14)
    width: Style.space(20)
    anchors.verticalCenter: parent.verticalCenter
    horizontalAlignment: Text.AlignHCenter
    text: slider.glyph
    color: slider.ink
    font.family: Style.font.menuFamily
    font.pixelSize: Style.font.title
    opacity: slider.usable ? 1 : 0.45
    TapHandler { enabled: slider.usable; onTapped: slider.glyphTapped() }
  }
  Item {
    id: track
    x: lead.x + lead.width + Style.space(14)
    width: parent.width - x - Style.space(16)
    height: Style.space(28)
    anchors.verticalCenter: parent.verticalCenter
    opacity: slider.usable ? (slider.dimmed ? 0.5 : 1) : 0.4
    readonly property real at: Math.max(0, Math.min(1, slider.level))
    Rectangle {
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width
      height: Style.space(6)
      color: slider.settings ? slider.settings.line : "gray"
    }
    Rectangle {
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width * track.at
      height: Style.space(6)
      color: slider.settings ? slider.settings.accent : "white"
    }
    Rectangle {
      x: parent.width * track.at - width / 2
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(16)
      height: Style.space(16)
      color: slider.ink
    }
    DragHandler {
      target: null
      enabled: slider.usable
      yAxis.enabled: false
      onCentroidChanged: if (active) slider.moved(Math.max(0, Math.min(1, centroid.position.x / track.width)))
    }
    TapHandler {
      enabled: slider.usable
      onTapped: function(point) { slider.moved(Math.max(0, Math.min(1, point.position.x / track.width))) }
    }
  }
}
