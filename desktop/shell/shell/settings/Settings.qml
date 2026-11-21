import QtQuick
import Quickshell
import Quickshell.Bluetooth
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import "SettingsLayout.js" as Layout
import "SettingsModel.js" as Model

// The Settings window: an ordinary window (it shows in Exposé and the dock,
// sits beside other windows, and opens maximised on tablets like every
// window), hosted by the shell so it shares the menu, the panels and the
// theme without a second copy of Qt in memory. It exists only while open:
// closing it destroys it and gives its memory back.
//
// Opened by `omarchy-settings [page]`, the launcher's Settings button, and
// IPC (`omarchy-shell omarchy.settings open <page>`), with deep links:
// a section ("appearance"), a page in it ("appearance/theme") or any menu
// entry ("setup.security").
Item {
  id: root

  property var shell: null
  property bool opened: false
  // Where the next open goes; the window reads it as it comes up, and again
  // when an open arrives while it is already showing.
  property string path: ""
  property int pathRevision: 0

  readonly property var menu: {
    var loaders = root.shell ? root.shell.panelLoaders : null
    var loader = loaders ? loaders["omarchy.menu"] : null
    return loader ? loader.item : null
  }

  function open(target) {
    root.path = String(target || "")
    root.pathRevision++
    if (root.opened) {
      // Already there: bring it forward.
      if (root.shell && root.shell.appLibrary) root.shell.appLibrary.focusToplevel("org\\.omarchy\\.settings")
      return
    }
    root.opened = true
  }

  // Whether Settings has a page for a menu entry: the launcher opens such a
  // submenu here rather than in the menu.
  function places(id) {
    if (!root.menu || !root.menu.items) return false
    return Model.sectionFor(Layout.SECTIONS, { items: root.menu.items, itemOrder: root.menu.itemOrder }, id) !== ""
  }

  function close() {
    root.opened = false
  }

  // About's facts: model, system, version, kernel, memory and storage, read
  // as the window opens so the page shows them whole. A line the system
  // cannot answer is left out.
  property var aboutFacts: []
  onOpenedChanged: if (opened) readAbout()
  function readAbout() { if (!aboutReader.running) { aboutReader.collected = ""; aboutReader.running = true } }
  Process {
    id: aboutReader
    command: ["bash", "-lc", [
      "model=$(tr -d '\\0' < /proc/device-tree/model 2>/dev/null); [[ -n $model ]] || model=$(cat /sys/class/dmi/id/product_name 2>/dev/null)",
      "printf 'device\\t%s\\n' \"$model\"",
      "printf 'name\\t%s\\n' \"$(cat /etc/hostname 2>/dev/null || uname -n)\"",
      "printf 'system\\t%s\\n' \"$(. /etc/os-release 2>/dev/null; echo \"$PRETTY_NAME\")\"",
      "printf 'version\\t%s\\n' \"$(omarchy-version 2>/dev/null || cat \"$OMARCHY_PATH/version\" 2>/dev/null)\"",
      "printf 'kernel\\t%s\\n' \"$(uname -r)\"",
      "printf 'memory\\t%s\\n' \"$(awk '/^MemTotal:/ { printf \"%.1f GB\", $2 / 1048576 }' /proc/meminfo)\"",
      "printf 'storage\\t%s\\n' \"$(df -B1 / 2>/dev/null | awk 'NR == 2 { printf \"%.0f GB of %.0f GB free\", $4 / 1e9, $2 / 1e9 }')\""
    ].join("\n")]
    property string collected: ""
    stdout: SplitParser { onRead: function(data) { aboutReader.collected += data + "\n" } }
    onExited: {
      var labels = {
        device: "settings.aboutDevice", name: "settings.aboutName", system: "settings.aboutSystem",
        version: "settings.aboutVersion", kernel: "settings.aboutKernel", memory: "settings.aboutMemory",
        storage: "settings.aboutStorage"
      }
      var out = []
      var lines = aboutReader.collected.split("\n")
      for (var i = 0; i < lines.length; i++) {
        var parts = lines[i].split("\t")
        if (!labels[parts[0]] || !parts[1] || !parts[1].trim()) continue
        out.push({ label: Commons.I18n.t(labels[parts[0]]), value: parts[1].trim() })
      }
      root.aboutFacts = out
    }
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open("")
  }

  // Bluetooth discovery while the Bluetooth page shows, and its end after,
  // here because the page (and the window) are gone by then. As the control
  // center does it: BlueZ refuses a start while the adapter powers up, and
  // only a stop after it confirmed the start ends the session, which would
  // otherwise keep the radio searching (and A2DP audio stuttering) until the
  // shell restarts.
  property bool bluetoothScan: false
  property bool owesDiscoveryStop: false
  readonly property var adapter: Bluetooth.defaultAdapter
  Timer {
    interval: 1000
    repeat: true
    triggeredOnStart: true
    running: root.bluetoothScan && root.adapter !== null && root.adapter.enabled && !root.adapter.discovering
    onTriggered: {
      root.owesDiscoveryStop = true
      root.adapter.discovering = true
    }
  }
  Timer {
    id: discoveryStop
    interval: 1000
    repeat: true
    property int attempts: 0
    running: !root.bluetoothScan && root.owesDiscoveryStop && root.adapter !== null && root.adapter.discovering === true
    onRunningChanged: if (running) attempts = 0
    onTriggered: {
      if (++attempts > 10) { root.owesDiscoveryStop = false; return }
      root.adapter.discovering = false
    }
  }
  // Once the search has ended, nothing is owed: a later one is someone else's.
  Connections {
    target: root.adapter
    function onDiscoveringChanged() {
      if (!root.bluetoothScan && root.adapter && !root.adapter.discovering) root.owesDiscoveryStop = false
    }
  }

  ShellIpc {
    target: "omarchy.settings"
    function open(page: string): void { root.open(page) }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
  }

  Loader {
    id: windowLoader
    active: root.opened
    asynchronous: false
    sourceComponent: SettingsWindow {
      host: root
      menu: root.menu
    }
    // A window torn down frees what it held; the engine collects it on its
    // own time otherwise, which on a small device is memory held for nothing.
    onActiveChanged: if (!active) Qt.callLater(function() { gc() })
  }
}
