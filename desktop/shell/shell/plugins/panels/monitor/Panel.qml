import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import qs.Commons as Commons

// Labwc brightness, rotation and stay-awake adapter for Omarchy's stock Display bar slot.
// Hyprland output switching/scaling is deliberately not exposed here.
Panel {
  id: root
  moduleName: "omarchy.monitor"
  ipcTarget: "omarchy.monitor"

  property bool brightnessAvailable: false
  property int brightnessPercent: 0
  property int queuedPercent: -1
  // The shell's idle service owns Stay Awake (state file, bar indicator, IPC).
  readonly property var idleService: bar?.shell?.firstPartyServiceFor("omarchy.idle")
  readonly property bool stayAwake: idleService ? idleService.stayAwake === true : false
  property bool rotationLocked: false
  property bool rotationLoaded: false
  readonly property string rotationHelper: (Quickshell.env("OMARCHY_PATH") ||
    Quickshell.env("HOME") + "/.local/share/omarchy-ipad") + "/bin/omarchy-rotation-lock"

  function refresh() {
    if (!readProc.running && !writeProc.running) readProc.running = true
    if (!rotationRead.running && !rotationWrite.running) rotationRead.running = true
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

  Process {
    id: rotationRead
    command: [root.rotationHelper, "status"]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          root.rotationLocked = JSON.parse(text).locked === true
          root.rotationLoaded = true
        } catch (_) { root.rotationLoaded = false }
      }
    }
  }
  Process {
    id: rotationWrite
    onExited: function(exitCode, exitStatus) { root.refresh() }
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
        Toggle {
          width: parent.width
          label: "Rotation lock"
          description: root.rotationLocked ? "Keep the current orientation" : "Turn the display with the iPad"
          checked: root.rotationLocked
          enabled: root.rotationLoaded && !rotationWrite.running
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          onClicked: {
            rotationWrite.command = [root.rotationHelper, root.rotationLocked ? "off" : "on"]
            rotationWrite.running = true
          }
        }
        Toggle {
          width: parent.width
          label: Commons.I18n.t("bar.stayAwake")
          description: root.stayAwake ? "The screen stays on; no automatic lock or sleep"
                                      : "Lock and sleep after the idle timeout"
          checked: root.stayAwake
          enabled: !!root.idleService
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          onClicked: root.idleService.setIdleEnabled(root.stayAwake)
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
