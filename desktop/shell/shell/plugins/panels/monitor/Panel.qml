import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import qs.Commons as Commons

// Labwc brightness-only adapter for Omarchy's stock Display bar slot.
// Hyprland output switching/scaling is deliberately not exposed here.
Panel {
  id: root
  moduleName: "omarchy.monitor"
  ipcTarget: "omarchy.monitor"

  property bool brightnessAvailable: false
  property int brightnessPercent: 0
  property int queuedPercent: -1

  function refresh() {
    if (!readProc.running && !writeProc.running) readProc.running = true
  }
  function setBrightness(value) {
    if (!brightnessAvailable) return
    var percent = Math.max(1, Math.min(100, Math.round(value)))
    root.brightnessPercent = percent
    if (writeProc.running) { root.queuedPercent = percent; return }
    writeProc.command = ["omarchy-brightness-display", "--no-osd", percent + "%"]
    writeProc.running = true
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  onOpenedChanged: if (opened) refresh()
  Component.onCompleted: refresh()

  Timer {
    interval: 5000
    repeat: true
    running: root.opened
    onTriggered: root.refresh()
  }
  Process {
    id: readProc
    command: ["omarchy-brightness-display"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var value = String(text || "").trim()
        root.brightnessAvailable = /^\d+$/.test(value)
        if (root.brightnessAvailable)
          root.brightnessPercent = Math.max(1, Math.min(100, parseInt(value, 10)))
      }
    }
  }
  Process {
    id: writeProc
    stdout: StdioCollector { waitForEnd: true }
    onRunningChanged: {
      if (running) return
      if (root.queuedPercent >= 0) {
        var next = root.queuedPercent
        root.queuedPercent = -1
        root.setBrightness(next)
      } else root.refresh()
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰍹"
    onPressed: function(b) { root.toggle() }
    onWheelMoved: function(delta) {
      if (root.brightnessAvailable) root.setBrightness(root.brightnessPercent + Math.sign(delta) * 5)
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: panel.loadedContent
    contentWidth: panel.fittedContentWidth(Style.space(320))
    contentHeight: panel.fittedContentHeight(panel.loadedContentHeight)

    content: PanelKeyCatcher {
      implicitHeight: column.implicitHeight
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (root.brightnessAvailable) root.setBrightness(root.brightnessPercent + (dx || -dy) * 5)
      }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(14)

        Text {
          width: parent.width
          text: "󰍹  " + Commons.I18n.t("monitor.display")
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
          textFormat: Text.PlainText
        }
        Text {
          width: parent.width
          text: root.brightnessAvailable ? Commons.I18n.t("monitor.brightness") + "  " + root.brightnessPercent + "%"
                                         : "Brightness unavailable: no backlight device"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          textFormat: Text.PlainText
        }
        PanelSlider {
          width: parent.width
          bar: root.bar
          visible: root.brightnessAvailable
          minimum: 1
          maximum: 100
          step: 1
          integer: true
          value: root.brightnessPercent
          onMoved: function(v) { root.setBrightness(v) }
          onReleased: function(v) { root.setBrightness(v) }
        }
      }
    }
  }
}
