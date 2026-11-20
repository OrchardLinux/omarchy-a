import QtQuick
import Quickshell
import Quickshell.Services.Pipewire
import qs.Commons
import qs.Commons as Commons
import "../plugins/panels/audio/Model.js" as AudioModel

// Sound: where it plays and what it listens to, as the control center's audio
// page offers them, in Settings' rows. The lists hold plain rows (a node's id
// and name), never the PipeWire nodes, which PipeWire deletes at any moment.
Item {
  id: page

  property var settings: null

  width: parent ? parent.width : 0
  height: column.height

  readonly property var nodes: Pipewire.nodes ? Pipewire.nodes.values : []
  readonly property var sink: Pipewire.defaultAudioSink
  readonly property var source: Pipewire.defaultAudioSource
  PwObjectTracker { objects: [page.sink, page.source].filter(function(n) { return !!n }) }

  function rows(output) {
    var list = []
    for (var i = 0; i < page.nodes.length; i++) {
      var n = page.nodes[i]
      if (!n || n.isStream) continue
      if (output ? !n.isSink : (n.isSink || !AudioModel.isAudioSource(n))) continue
      if (output && AudioNodes.platformHides(n.name, [])) continue
      list.push({ id: n.id, name: String(n.name || ""), label: AudioModel.nodeLabel(n, Commons.I18n.t),
                  glyph: output ? AudioModel.sinkGlyph(n) : AudioModel.sourceGlyph(n) })
    }
    return list
  }
  readonly property var outputs: rows(true)
  readonly property var inputs: rows(false)

  function nodeFor(row) {
    for (var i = 0; i < page.nodes.length; i++) {
      var n = page.nodes[i]
      if (n && n.id === row.id && String(n.name) === row.name) return n
    }
    return null
  }

  // As the control center chooses: Quickshell's default, and the command that
  // makes it stick for the session.
  function choose(row, output) {
    var node = page.nodeFor(row)
    if (!node) return
    if (output) Pipewire.preferredDefaultAudioSink = node
    else if (node.audio) Pipewire.preferredDefaultAudioSource = node
    Quickshell.execDetached([output ? "omarchy-audio-output-set-default" : "omarchy-audio-input-set-default",
                             String(node.id), String(node.name)])
  }

  Column {
    id: column
    width: page.width
    spacing: Style.space(14)

    SettingsBox {
      settings: page.settings
      width: parent.width
      title: Commons.I18n.t("settings.output")
      visible: page.outputs.length > 0
      VolumeRow {
        node: page.sink
        first: true
      }
      Repeater {
        model: page.outputs
        SettingsItem {
          required property var modelData
          settings: page.settings
          glyph: modelData.glyph
          label: modelData.label
          checked: !!page.sink && page.sink.id === modelData.id
          onActivated: page.choose(modelData, true)
        }
      }
    }

    SettingsBox {
      settings: page.settings
      width: parent.width
      title: Commons.I18n.t("settings.input")
      visible: page.inputs.length > 0
      VolumeRow {
        node: page.source
        first: true
      }
      Repeater {
        model: page.inputs
        SettingsItem {
          required property var modelData
          settings: page.settings
          glyph: modelData.glyph
          label: modelData.label
          checked: !!page.source && page.source.id === modelData.id
          onActivated: page.choose(modelData, false)
        }
      }
    }

    Text {
      visible: page.outputs.length === 0 && page.inputs.length === 0
      text: Commons.I18n.t("settings.noAudioDevices")
      color: page.settings ? page.settings.faint : "gray"
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
    }
  }

  // The level of the device in use, and its mute on the glyph.
  component VolumeRow: Item {
    id: volumeRow
    property var node: null
    property bool first: false
    readonly property bool usable: !!node && !!node.audio
    readonly property real level: usable ? Math.min(1, node.audio.volume) : 0
    readonly property bool muted: usable && node.audio.muted
    width: parent ? parent.width : 0
    height: page.settings ? page.settings.rowHeight + Style.space(6) : 48

    Text {
      id: muteGlyph
      x: Style.space(14)
      width: Style.space(20)
      anchors.verticalCenter: parent.verticalCenter
      horizontalAlignment: Text.AlignHCenter
      text: volumeRow.muted ? "󰖁" : "󰕾"
      color: page.settings ? page.settings.text : "white"
      font.family: Style.font.menuFamily
      font.pixelSize: Style.font.title
      TapHandler {
        enabled: volumeRow.usable
        onTapped: volumeRow.node.audio.muted = !volumeRow.node.audio.muted
      }
    }
    Item {
      id: track
      x: muteGlyph.x + muteGlyph.width + Style.space(14)
      width: parent.width - x - Style.space(16)
      height: Style.space(28)
      anchors.verticalCenter: parent.verticalCenter
      opacity: volumeRow.usable ? (volumeRow.muted ? 0.5 : 1) : 0.4
      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        height: Style.space(6)
        color: page.settings ? page.settings.line : "gray"
      }
      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width * volumeRow.level
        height: Style.space(6)
        color: page.settings ? page.settings.accent : "white"
      }
      Rectangle {
        x: parent.width * volumeRow.level - width / 2
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(16)
        height: Style.space(16)
        color: page.settings ? page.settings.text : "white"
      }
      // The level goes where the finger or the pointer is, along the way.
      DragHandler {
        id: drag
        target: null
        enabled: volumeRow.usable
        xAxis.enabled: true
        yAxis.enabled: false
        onCentroidChanged: if (active) volumeRow.set(centroid.position.x)
      }
      TapHandler {
        enabled: volumeRow.usable
        onTapped: function(point) { volumeRow.set(point.position.x) }
      }
    }
    function set(x) {
      if (!usable) return
      node.audio.volume = Math.max(0, Math.min(1, x / track.width))
      if (node.audio.muted && x > 0) node.audio.muted = false
    }
  }
}
