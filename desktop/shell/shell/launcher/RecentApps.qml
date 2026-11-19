import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// When each app was last used: the moment one of its windows gained or lost
// focus, or closed. Windows come from the toplevel list Exposé uses, matched
// to the desktop entry that claims them. Kept in a small state file so the
// launcher's Recent apps outlive the session.
Item {
  id: root

  // desktop id -> epoch ms
  property var used: ({})
  // Newest first, [{ id, time }]: a property, so views follow it.
  readonly property var rows: {
    var out = []
    for (var id in root.used) out.push({ id: id, time: root.used[id] })
    out.sort(function(a, b) { return b.time - a.time })
    return out
  }
  // Nothing is written before the file has been read, or a stamp made at
  // startup would replace every older one.
  property bool loaded: false
  readonly property string statePath: (Quickshell.env("XDG_STATE_HOME") || (Quickshell.env("HOME") + "/.local/state")) + "/omarchy/launcher-recent-apps.json"

  property var lastActive: null
  property string lastActiveId: ""
  // The windows seen last time with their app, since a closed one may be
  // gone before its app can be read.
  property var known: []

  function desktopIdFor(toplevel) {
    if (!toplevel) return ""
    var entry = DesktopEntries.heuristicLookup(String(toplevel.appId || ""))
    return entry ? String(entry.id || "") : ""
  }

  function stamp(id) {
    if (!id) return
    var next = ({})
    for (var k in root.used) next[k] = root.used[k]
    next[id] = Date.now()
    root.used = next
    saveTimer.restart()
  }

  // Newest first: [{ id, time }]
  function recent(limit) {
    var rows = []
    for (var id in root.used) rows.push({ id: id, time: root.used[id] })
    rows.sort(function(a, b) { return b.time - a.time })
    return limit ? rows.slice(0, limit) : rows
  }

  function forget(id) {
    if (!(id in root.used)) return
    var next = ({})
    for (var k in root.used) if (k !== id) next[k] = root.used[k]
    root.used = next
    saveTimer.restart()
  }

  Connections {
    target: ToplevelManager
    function onActiveToplevelChanged() {
      var active = ToplevelManager.activeToplevel
      if (root.lastActiveId) root.stamp(root.lastActiveId)
      root.lastActive = active
      root.lastActiveId = root.desktopIdFor(active)
      if (root.lastActiveId) root.stamp(root.lastActiveId)
    }
  }

  Connections {
    target: ToplevelManager.toplevels
    function onValuesChanged() { root.syncWindows() }
  }

  function syncWindows() {
    var values = ToplevelManager.toplevels.values
    var next = []
    for (var i = 0; i < values.length; i++) next.push({ window: values[i], id: root.desktopIdFor(values[i]) })
    for (var j = 0; j < root.known.length; j++) {
      if (values.indexOf(root.known[j].window) < 0) root.stamp(root.known[j].id)
    }
    root.known = next
  }

  Timer {
    id: saveTimer
    interval: 1500
    onTriggered: if (root.loaded) stateFile.setText(JSON.stringify(root.used))
  }

  FileView {
    id: stateFile
    path: root.statePath
    printErrors: false
    atomicWrites: true
    // Read while this item is built, before any handler is attached, so
    // Component.onCompleted takes the result rather than onLoaded.
    blockLoading: true
  }

  function readState() {
    if (root.loaded) return
    var raw = ""
    try { raw = stateFile.text() } catch (e) { raw = "" }
    try {
      var parsed = raw ? JSON.parse(raw) : null
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        // Stamps made before the file was read win over its older ones.
        for (var k in root.used) parsed[k] = Math.max(Number(parsed[k]) || 0, root.used[k])
        root.used = parsed
      }
    } catch (e) { }
    root.loaded = true
    root.stampOpen()
  }

  // An open window's app that was never stamped (it was opened before the
  // shell started) counts as used now; one with a stamp keeps it.
  function stampOpen() {
    var values = ToplevelManager.toplevels.values
    var next = ({})
    for (var k in root.used) next[k] = root.used[k]
    var now = Date.now()
    for (var i = 0; i < values.length; i++) {
      var id = root.desktopIdFor(values[i])
      if (id && !(id in next)) next[id] = now
    }
    root.used = next
    saveTimer.restart()
  }

  Component.onCompleted: {
    Quickshell.execDetached(["mkdir", "-p", root.statePath.substring(0, root.statePath.lastIndexOf("/"))])
    syncWindows()
    readState()
  }
}
