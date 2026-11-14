import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import qs.Commons as Commons
import "Model.js" as Model

// Labwc brightness, scale, rotation and stay-awake adapter for Omarchy's stock Display bar slot.
// The Scale row is upstream's (presets, availableScales, cleanScale labels,
// setScale through omarchy-hyprland-monitor-scaling); the output comes from
// `wlr-randr --json` (the first enabled one) instead of Hyprland, and the
// shown scale updates as soon as a pill is clicked. Hyprland output switching,
// resolution, mirror and layout are not exposed here.
Panel {
  id: root
  moduleName: "omarchy.monitor"
  ipcTarget: "omarchy.monitor"

  property bool brightnessAvailable: false
  property int brightnessPercent: 0
  property int queuedPercent: -1
  // Ambient-light auto-brightness (omarchy-auto-brightness); hidden when the tool is absent.
  property bool autoAvailable: false
  property bool autoOn: false
  // The shell's idle service owns Stay Awake (state file, bar indicator, IPC).
  readonly property var idleService: bar?.shell?.firstPartyServiceFor("omarchy.idle")
  readonly property bool stayAwake: idleService ? idleService.stayAwake === true : false
  property bool rotationLocked: false
  property bool rotationLoaded: false
  // The shown output, from wlr-randr: name, mode size (before rotation), scale.
  property string outputName: ""
  property int outputWidth: 0
  property int outputHeight: 0
  property real outputScale: 0
  property var queuedScale: null
  readonly property var scalePresets: ["1", "1.25", "1.6", "2", "3", "4"]
  // The presets this mode can reach, one per clean scale, as upstream offers
  // them, and the one in use. Matched in one binding, on the plain array: once
  // it is handed through a QML property it is no longer one Array.isArray accepts.
  readonly property var scaleChoice: {
    if (!(outputWidth > 0)) return { scales: [], index: -1 }
    var list = Model.availableScales(scalePresets, outputWidth, outputHeight)
    return { scales: list, index: Model.matchingScaleIndex(list, outputScale, outputWidth, outputHeight) }
  }
  readonly property var scales: scaleChoice.scales
  readonly property int scaleIndex: scaleChoice.index
  readonly property string rotationHelper: (Quickshell.env("OMARCHY_PATH") ||
    Quickshell.env("HOME") + "/.local/share/omarchy-ipad") + "/bin/omarchy-rotation-lock"

  function setAuto(on) {
    if (!autoAvailable || autoWriteProc.running) return
    root.autoOn = on  // optimistic: the switch moves at once
    autoWriteProc.command = ["omarchy-auto-brightness", on ? "on" : "off"]
    autoWriteProc.running = true
  }

  function refresh() {
    if (!readProc.running && !writeProc.running) readProc.running = true
    if (!autoReadProc.running && !autoWriteProc.running) autoReadProc.running = true
    if (!rotationRead.running && !rotationWrite.running) rotationRead.running = true
    if (!outputRead.running && !scaleWrite.running) outputRead.running = true
  }
  function setScale(name, scale) {
    // Show the clean scale it lands on right away; the next read confirms it.
    var effective = Number(Model.cleanScale(scale, root.outputWidth, root.outputHeight))
    if (isFinite(effective) && effective > 0) root.outputScale = effective
    if (scaleWrite.running) { root.queuedScale = { name: name, scale: scale }; return }
    scaleWrite.command = ["omarchy-hyprland-monitor-scaling", "--monitor", name, String(scale)]
    scaleWrite.running = true
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
    id: autoReadProc
    command: ["omarchy-auto-brightness", "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var m = /^auto-brightness:\s*(on|off)/m.exec(String(text || ""))
        root.autoAvailable = m !== null
        if (m) root.autoOn = m[1] === "on"
      }
    }
  }
  Process {
    id: rotationWrite
    onExited: function(exitCode, exitStatus) { root.refresh() }
  }

  Process {
    id: autoWriteProc
    stdout: StdioCollector { waitForEnd: true }
    onRunningChanged: if (!running) root.refresh()
  }
  Process {
    id: outputRead
    command: ["wlr-randr", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var parsed = Model.parseDisplays(text)
        var output = null
        for (var i = 0; i < parsed.displays.length && !output; i++)
          if (parsed.displays[i] && parsed.displays[i].enabled) output = parsed.displays[i]
        var mode = null
        var modes = output && output.modes ? output.modes : []
        for (var j = 0; j < modes.length && !mode; j++)
          if (modes[j] && modes[j].current) mode = modes[j]
        if (!output || !mode) {
          root.outputName = ""
          root.outputWidth = 0
          root.outputHeight = 0
          return
        }
        root.outputName = String(output.name || "")
        root.outputWidth = Number(mode.width) || 0
        root.outputHeight = Number(mode.height) || 0
        root.outputScale = Number(output.scale) || 0
      }
    }
  }
  Process {
    id: scaleWrite
    onRunningChanged: {
      if (running) return
      if (root.queuedScale) {
        var next = root.queuedScale
        root.queuedScale = null
        root.setScale(next.name, next.scale)
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
        Toggle {
          width: parent.width
          visible: root.autoAvailable
          label: Commons.I18n.t("monitor.autoBrightness")
          description: Commons.I18n.t("monitor.autoBrightnessHint")
          checked: root.autoOn
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          onClicked: root.setAuto(!root.autoOn)
        }

        // ---------- Scale ----------
        PanelSeparator {
          width: parent.width
          visible: root.scales.length > 0
          foreground: root.bar.foreground
        }
        Column {
          visible: root.scales.length > 0
          width: parent.width
          spacing: Style.space(6)

          PanelSectionHeader {
            text: Commons.I18n.t("monitor.scale")
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
          }

          Grid {
            id: scaleGrid
            width: parent.width
            columns: Math.max(1, root.scales.length)
            spacing: Style.spacing.xs

            readonly property real cellWidth: (width - spacing * (columns - 1)) / columns

            Repeater {
              model: root.scales

              ScalePill {
                required property string modelData
                required property int index

                scaleValue: modelData
                scaleIndex: index
                width: scaleGrid.cellWidth
              }
            }
          }
        }
      }
    }
  }

  component ScalePill: Button {
    id: pill
    required property string scaleValue
    required property int scaleIndex

    text: root.outputWidth > 0 ? Commons.I18n.formatNumber(Model.cleanScale(scaleValue, root.outputWidth, root.outputHeight)) + "x" : ""
    fontSize: Style.font.caption
    foreground: root.bar.foreground
    fontFamily: root.bar.fontFamily
    horizontalPadding: Style.spacing.sm
    verticalPadding: Style.spacing.controlPaddingY
    bordered: true

    active: root.scaleIndex === scaleIndex

    onClicked: if (root.outputName) root.setScale(root.outputName, scaleValue)
  }
}
