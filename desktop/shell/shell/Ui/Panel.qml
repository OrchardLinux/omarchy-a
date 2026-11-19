import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons

// Base item for plugin popup widgets. Many first-party plugins expose a bar
// button plus a popup from one QML entry point; this base owns the shared
// IPC-backed open/close lifecycle while implementations own button behavior,
// keyboard navigation, and content.
Item {
  id: root

  property QtObject bar: null
  property string moduleName: ""
  property var settings: ({})
  property string ipcTarget: ""
  property bool manageIpc: true
  property alias controller: panelController
  property bool popoutSwitching: false
  property bool popoutSwitchClosing: false

  // Orchard: a host (the control center) can show this panel's content as
  // one of its pages instead of the popup. Hosted, opening shows the page,
  // closing (Esc in the content) goes back, the popup stays closed and the
  // IPC target is the bar's panel's alone.
  property var host: null
  property bool hostShown: false
  readonly property bool hosted: host !== null
  readonly property bool opened: hosted ? hostShown : panelController.open
  readonly property bool popupOpen: !hosted && panelController.open
  readonly property color barForeground: bar ? bar.barForeground : Commons.Color.foreground

  function open() { if (hosted) host.showPage(root); else panelController.show() }
  function close() { if (hosted) host.leavePage(root); else panelController.hide() }
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { popoutSwitchClosing = false })
  }
  function toggle() { opened ? close() : open() }
  function switchPanel(direction) {
    if (bar && typeof bar.switchPanelFrom === "function") return bar.switchPanelFrom(root, direction)
    return false
  }

  // Read a single value from this panel's inline shell.json entry, with a
  // fallback for missing/null values. Matches BarWidget.setting().
  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  PanelController {
    id: panelController
  }

  ShellIpc {
    // A panel that answers its target itself leaves this one without one.
    target: root.manageIpc && !root.hosted ? root.ipcTarget : ""

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { if (typeof root.refresh === "function") root.refresh() }
  }

}
