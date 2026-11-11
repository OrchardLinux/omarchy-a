import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "ActivityModel.js" as ActivityModel

// CPU or memory use in percent, and the way into Omactivity, the task manager.
//
// A tap opens Omactivity on the tab of the figure shown, or brings its window
// to the front when it is already open. A long press (a right click with a
// mouse) switches between CPU and memory, as it switches the battery
// percentage on the power widget.
//
// Each reading is one small file, /proc/stat or /proc/meminfo, and no process
// is started for it. Drawn as text and a font glyph only: the shell renders in
// software on most boards.
BarWidget {
  id: root
  moduleName: "omarchy.activity"

  readonly property string mode: setting("mode", "cpu") === "memory" ? "memory" : "cpu"
  readonly property int interval: Math.max(1, Math.round(Number(setting("interval", 3))) || 3)
  // A narrow bar (a phone's) has room for the figure but not for its icon.
  readonly property bool compact: !!bar && bar.narrow === true && !vertical

  // Whole percent, or -1 before the first reading.
  property int percent: -1
  property var cpuReading: null

  readonly property string tooltip: mode === "memory" ? I18n.t("bar.activityMemory") : I18n.t("bar.activityCpu")

  function label(padded) {
    return ActivityModel.label(percent, percent < 0 ? "" : I18n.formatNumber(percent), padded)
  }

  function take(text) {
    if (mode === "memory") {
      percent = ActivityModel.memoryPercent(text)
      return
    }
    // CPU use is the change between two readings: the first shows nothing.
    var reading = ActivityModel.cpuTimes(text)
    var next = ActivityModel.cpuPercent(cpuReading, reading)
    if (next >= 0 || !cpuReading) percent = next
    cpuReading = reading
  }

  function toggleMode() {
    root.settings = Object.assign({}, root.settings, { mode: root.mode === "memory" ? "cpu" : "memory" })
    if (root.bar && root.bar.shell) root.bar.shell.updateEntryInline(root.moduleName, root.settings)
  }

  function openActivity() {
    var windows = ToplevelManager.toplevels.values
    for (var i = 0; i < windows.length; i++) {
      if (String(windows[i].appId || "") !== "omactivity") continue
      windows[i].activate()
      return
    }
    // Without a login shell in between: this has to work when memory is short.
    Quickshell.execDetached(["uwsm-app", "--", "omactivity", "--tab", root.mode])
  }

  function press(button) {
    if (button === Qt.RightButton) root.toggleMode()
    else if (button === Qt.LeftButton) root.openActivity()
  }

  onModeChanged: {
    percent = -1
    cpuReading = null
  }

  implicitWidth: face.item ? face.item.implicitWidth : 0
  implicitHeight: face.item ? face.item.implicitHeight : 0

  // Changing the path reads the other file at once.
  FileView {
    id: source
    path: root.mode === "memory" ? "/proc/meminfo" : "/proc/stat"
    printErrors: false
    onLoaded: root.take(text())
    onLoadFailed: root.percent = -1
  }

  Timer {
    // Soon after the first reading, so a CPU figure is there within a second.
    interval: root.percent < 0 ? 500 : root.interval * 1000
    running: root.visible
    repeat: true
    onTriggered: source.reload()
  }

  Loader {
    id: face
    anchors.fill: parent
    sourceComponent: root.compact ? figure : iconAndFigure
  }

  Component {
    id: iconAndFigure

    BarIconButton {
      bar: root.bar
      text: root.mode === "memory" ? "\udb80\udf5b" : "\uf4bc"
      labelText: vertical ? "" : root.label(true)
      labelFontSize: Math.max(13, Style.font.body)
      slotSize: Style.bar.iconSlot * (vertical ? 1 : 2)
      tooltipText: root.tooltip
      onPressed: function(button) { root.press(button) }
    }
  }

  Component {
    id: figure

    WidgetButton {
      bar: root.bar
      text: root.label(false)
      fixedWidth: Style.bar.iconSlot
      tooltipText: root.tooltip
      onPressed: function(button) { root.press(button) }
    }
  }
}
