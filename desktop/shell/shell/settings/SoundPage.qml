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
  component VolumeRow: SettingsSlider {
    property var node: null
    readonly property bool live: !!node && !!node.audio
    settings: page.settings
    usable: live
    level: live ? node.audio.volume : 0
    dimmed: live && node.audio.muted
    glyph: dimmed ? "\udb81\udd81" : "\udb81\udd7e"
    onMoved: function(value) {
      if (!live) return
      node.audio.volume = value
      if (node.audio.muted && value > 0) node.audio.muted = false
    }
    onGlyphTapped: if (live) node.audio.muted = !node.audio.muted
  }
}
