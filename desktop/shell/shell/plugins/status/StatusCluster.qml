import QtQuick
import Quickshell
import Quickshell.Services.Pipewire
import qs.Commons
import qs.Commons as Commons
import "../panels/network" as Network
import "../panels/bluetooth" as BluetoothStatus
import "../panels/power" as Power

// The status cluster (SHELL-SPEC, step 2): mic muted, rotation lock, Focus
// and Stay Awake while on, Bluetooth while on, Wi-Fi, battery percentage and
// glyph. The bar's and the lock's: the host passes what only the shell knows
// (Focus, Stay Awake) and decides whether a tap does anything (activated,
// with the module).
Row {
  id: root

  property bool stayAwake: false
  property bool focusMode: false
  property bool rotationLocked: rotation.locked
  property color color: Commons.Color.bar.text
  property int glyphSize: Style.font.body
  property int textSize: Style.font.bodySmall
  property bool interactive: false
  signal activated(string module)

  spacing: Style.space(10)

  Network.Status { id: network }
  BluetoothStatus.Status { id: bluetooth }
  Power.Status { id: battery }
  RotationLock { id: rotation }

  readonly property var source: Pipewire.defaultAudioSource
  PwObjectTracker { objects: root.source ? [root.source] : [] }
  // A virtual source is untyped in Quickshell; its mute goes through wpctl.
  readonly property bool micMuted: UntypedInput.active
    ? (UntypedInput.known && UntypedInput.muted)
    : !!(source && source.audio && source.audio.muted)

  readonly property var items: [
    { module: "microphone", glyph: "󰍭", shown: root.micMuted },
    { module: "rotation", glyph: "󰝳", shown: root.rotationLocked },
    { module: "focus", glyph: "󰖔", shown: root.focusMode },
    { module: "stayAwake", glyph: "", shown: root.stayAwake },
    { module: "bluetooth", glyph: bluetooth.icon, shown: bluetooth.enabled },
    { module: "network", glyph: network.icon, shown: network.icon !== "" },
    { module: "battery", glyph: battery.icon, shown: battery.batteryPresent,
      label: battery.displayedPercentage === null ? "" : Commons.I18n.formatNumber(battery.displayedPercentage) + "%" }
  ]

  Repeater {
    model: root.items
    Item {
      id: entry
      required property var modelData
      visible: modelData.shown && modelData.glyph !== ""
      height: Math.max(glyph.implicitHeight, label.implicitHeight)
      width: entryRow.implicitWidth
      Row {
        id: entryRow
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(3)
        Text {
          id: label
          anchors.verticalCenter: parent.verticalCenter
          visible: text !== ""
          textFormat: Text.PlainText
          text: entry.modelData.label || ""
          color: root.color
          font.family: Style.font.family
          font.pixelSize: root.textSize
        }
        Text {
          id: glyph
          anchors.verticalCenter: parent.verticalCenter
          text: entry.modelData.glyph
          color: root.color
          font.family: Style.font.family
          font.pixelSize: root.glyphSize
        }
      }
      MouseArea {
        anchors.fill: parent
        anchors.margins: -Style.space(4)
        enabled: root.interactive
        cursorShape: Qt.PointingHandCursor
        onClicked: root.activated(entry.modelData.module)
      }
    }
  }
}
