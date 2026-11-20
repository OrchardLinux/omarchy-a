import QtQuick
import Quickshell
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

  function toggle() {
    if (root.opened) root.close()
    else root.open("")
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
