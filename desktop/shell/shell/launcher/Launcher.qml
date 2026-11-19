import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "LauncherModel.js" as Model
import "../plugins/menu/MenuModel.js" as MenuModel

// The launcher: every app, the Omarchy menu's actions, the session, and one
// search over apps, actions and the whole menu. It opens from Home, Super,
// Super+Space and the bar's logo (`omarchy-shell omarchy.dock apps`).
//
// Labels, glyphs, `when`, `checked` and actions come from the Omarchy menu
// itself: the launcher reads the loaded menu plugin's rows and guard results
// and runs entries through it, so it never keeps a second copy of either.
Item {
  id: root

  property var shell: null
  property var appLibrary: null
  // Keep in Dock / Remove from Dock, only where a dock runs.
  property var dock: null

  readonly property var menu: {
    var loaders = root.shell ? root.shell.panelLoaders : null
    var loader = loaders ? loaders["omarchy.menu"] : null
    return loader ? loader.item : null
  }

  property bool opened: false
  // The search field has focus: the tabs make way for search.
  property bool searching: false
  property string query: ""
  // Keyboard cursor: a zone (tabs, body, footer) and an index in it. It
  // shows once a key moves it; touch never leaves a highlight behind.
  property string zone: "body"
  property int cursor: 0
  property bool cursorShown: false

  property var apps: []
  property bool appsStale: true
  property var recentFiles: []
  property double now: Date.now()

  // The app whose menu is open, where, and whether it may be uninstalled.
  property var menuEntry: null
  property point menuPoint
  property bool menuRemovable: false
  property var uninstallEntry: null

  RecentApps { id: recentAppStamps }

  // ------------------------------------------------------------- geometry

  readonly property real screenWidth: panel.width
  readonly property real screenHeight: panel.height
  readonly property bool phone: Model.isPhone(screenWidth, screenHeight)
  readonly property bool landscape: screenWidth > screenHeight
  readonly property int columns: Model.columnsFor(screenWidth, screenHeight, phone)
  readonly property int sideMargin: phone ? Style.space(16) : (landscape ? Style.space(56) : Style.space(32))
  readonly property int contentWidth: Math.max(0, screenWidth - sideMargin * 2)
  readonly property real cellWidth: contentWidth / Math.max(1, columns)
  readonly property int iconSize: Math.round(Math.min(Style.space(56), cellWidth * 0.6))
  readonly property int labelLines: 2
  readonly property int cellHeight: Style.space(10) + iconSize + Style.spacing.md + Math.ceil(labelMetrics.height) * labelLines + Style.space(10)
  readonly property int barInset: Style.bar.sizeHorizontal
  // A short screen (a phone held sideways) keeps the header tight: every
  // point there is a point less for the apps.
  readonly property bool compact: screenHeight > 0 && screenHeight < 500
  // The smallest thing a finger is asked to hit (Apple's 44 × 44 points).
  readonly property int touchMin: Style.space(44)
  readonly property int searchHeight: Style.space(compact ? 36 : (phone ? 44 : 48))
  readonly property int gap: Style.space(compact ? 8 : (phone ? 12 : 16))
  // Room the page dots take below a phone's app pages.
  readonly property int dotsHeight: phone ? Style.space(compact ? 14 : 20) : 0
  readonly property int rowHeight: Style.space(phone ? 52 : 58)
  readonly property int listColumns: phone ? 1 : 2
  // The launcher is a menu surface: its text, selection and background are
  // the theme's menu roles; controls take the [controls] state tokens.
  readonly property color text: Commons.Color.menu.text
  // Secondary lines, placeholders and quiet tabs, as the shell's other
  // search fields draw them.
  readonly property color faint: Util.alpha(Commons.Color.menu.text, 0.58)
  readonly property color hairline: Style.normalBorderColor
  readonly property var selectedBorderSpec: Border.surfaceSpec("menu", "selected-border", Commons.Color.menu.selectedBorder, 0)
  // Where the keyboard is: a ring in the theme's accent, at its focus border
  // width. It shows once a key has
  // moved the cursor; a finger never sees it.
  readonly property var focusRing: Border.flat(Commons.Color.accent, Math.max(1, Style.focusBorderWidth))

  FontMetrics {
    id: labelMetrics
    font.family: Style.font.menuFamily
    font.pixelSize: Style.font.body
  }

  // --------------------------------------------------------- menu sources

  function entry(id) {
    return root.menu && root.menu.items ? (root.menu.items[id] || null) : null
  }

  function shown(e) {
    return !!e && !!root.menu && root.menu.whenResults !== undefined && root.menu.isVisible(e)
  }

  // A row under a section whose `when` hides it (Agent, without the agent
  // commands) has nothing to run, so search leaves it out too.
  function ancestorsShown(e) {
    var m = root.menu
    var guards = m.whenResults
    var current = e && m.items[e.parent]
    for (var guard = 0; current && current.id !== "root" && guard < 32; guard++) {
      if (current.when && guards && guards[current.id] === false) return false
      current = m.items[current.parent]
    }
    return true
  }

  function isOff(e) {
    return !!e && !!root.menu && root.menu.disabledResults !== undefined && root.menu.isDisabled(e)
  }

  function glyphFont(e) {
    return e && e.iconFont ? e.iconFont : Style.font.menuFamily
  }

  // Lock, Suspend, Logout, Reboot, Shutdown, and Hibernate or Screensaver
  // where their `when` allows: the menu's System list without About.
  readonly property var sessionEntries: {
    var m = root.menu
    if (!m || !m.items) return []
    var guards = m.whenResults
    var alt = MenuModel.altVariantIds(m.items, m.itemOrder)
    var ids = Model.sessionIds(m.itemOrder, m.items, alt)
    var out = []
    for (var i = 0; i < ids.length; i++) {
      var e = m.items[ids[i]]
      if (root.shown(e)) out.push(e)
    }
    return out
  }

  readonly property var actionGroups: {
    var m = root.menu
    if (!m || !m.items) return []
    var guards = m.whenResults
    var out = []
    for (var g = 0; g < Model.ACTION_GROUPS.length; g++) {
      var group = Model.ACTION_GROUPS[g]
      var ids = Model.groupIds(group, m.itemOrder, m.items)
      var entries = []
      for (var i = 0; i < ids.length; i++) {
        var e = m.items[ids[i]]
        if (root.shown(e)) entries.push(e)
      }
      if (entries.length === 0) continue
      var heading = group.menu ? (m.items[group.menu] ? m.items[group.menu].label : "") : Commons.I18n.t("launcher.tools")
      out.push({ key: group.key, label: heading, color: group.color, entries: entries })
    }
    return out
  }

  readonly property int actionCount: {
    var n = 0
    for (var i = 0; i < actionGroups.length; i++) n += actionGroups[i].entries.length
    return n
  }

  function groupColor(name) {
    if (name === "cyan") return Commons.Color.cyan
    if (name === "yellow") return Commons.Color.yellow
    return Commons.Color.blue
  }

  // ----------------------------------------------------------- search data

  // What a typed search finds: matching apps for the top row, and the menu's
  // matches grouped by the section they come from, best section first.
  readonly property var search: {
    var q = root.query.trim()
    var out = { apps: [], groups: [], appBest: 0 }
    if (!q) return out
    var m = root.menu
    var appRows = root.appLibrary ? root.appLibrary.sortedEntries(q).slice(0, root.columns) : []
    out.apps = appRows.map(function(row) { return { kind: "app", app: row.entry } })
    if (appRows.length > 0) {
      var top = appRows[0].score
      out.appBest = (top >= 9500 ? 5 : (top >= 7600 ? 25 : 45)) * 1000
    }
    if (m && m.items) {
      var guards = m.whenResults
      var byTop = ({})
      for (var i = 0; i < m.itemOrder.length; i++) {
        var e = m.items[m.itemOrder[i]]
        if (!e || e.id === "root" || e.kind === "app" || e.id === "apps") continue
        if (!m.matchesQuery(e, q) || !root.ancestorsShown(e)) continue
        var topId = Model.topLevelId(m.items, e.id)
        if (!topId || topId === "apps") continue
        var score = m.searchScore(e, q)
        if (!byTop[topId]) {
          byTop[topId] = { key: topId, label: m.items[topId] ? m.items[topId].label : topId, best: score, rows: [] }
          out.groups.push(byTop[topId])
        }
        byTop[topId].best = Math.min(byTop[topId].best, score)
        byTop[topId].rows.push({ kind: "menu", entry: e, score: score })
      }
      for (var k in byTop) {
        byTop[k].rows.sort(function(a, b) { return a.score - b.score })
        byTop[k].rows = byTop[k].rows.slice(0, 6)
      }
    }
    out.groups.sort(function(a, b) { return a.best - b.best })
    var start = out.apps.length
    for (var g = 0; g < out.groups.length; g++) {
      out.groups[g].start = start
      start += out.groups[g].rows.length
    }
    return out
  }

  // The search's rows in keyboard order: the apps, then each section.
  readonly property var resultRows: {
    var out = search.apps.slice()
    for (var g = 0; g < search.groups.length; g++) out = out.concat(search.groups[g].rows)
    return out
  }

  // The best match, which Enter runs: an app when it matches as well as the
  // best menu entry, else that entry.
  readonly property int topIndex: {
    if (search.apps.length === 0 || search.groups.length === 0) return 0
    return search.appBest <= search.groups[0].best ? 0 : search.apps.length
  }



  readonly property var recentAppRows: {
    var stamps = recentAppStamps.rows
    // The desktop entries arrive after startup: look again when they do.
    var entries = DesktopEntries.applications.values.length + root.apps.length
    var out = []
    for (var i = 0; i < stamps.length && out.length < 6; i++) {
      var app = DesktopEntries.byId(stamps[i].id)
      if (!app || app.noDisplay || (root.appLibrary && root.appLibrary.isHiddenEntry(app))) continue
      out.push({ kind: "app", app: app, time: stamps[i].time })
    }
    return out
  }

  readonly property var recentRows: recentAppRows.concat(recentFiles.map(function(file) { return { kind: "file", file: file } }))

  // ------------------------------------------------------------- the pages

  // Apps, Actions and (on a phone) System sit side by side and swipe like
  // mobile tabs. A phone's apps take several pages of their own, so the
  // pages are: every app page, then Actions, then System.
  readonly property bool showsAddApps: !root.phone
  readonly property int appTileCount: apps.length + (showsAddApps ? 1 : 0)
  property real pagerHeight: 0
  readonly property int rowsPerPage: Math.max(1, Math.floor((pagerHeight - dotsHeight) / Math.max(1, cellHeight)))
  readonly property int perPage: rowsPerPage * columns
  readonly property int appPageCount: phone ? Math.max(1, Math.ceil(apps.length / perPage)) : 1
  readonly property var tabs: root.phone ? ["apps", "actions", "system"] : ["apps", "actions"]
  readonly property var pages: {
    var out = []
    for (var i = 0; i < appPageCount; i++) out.push({ tab: "apps", page: i })
    out.push({ tab: "actions", page: 0 })
    if (root.phone) out.push({ tab: "system", page: 0 })
    return out
  }
  property int pageIndex: 0
  readonly property string tab: pages[Math.max(0, Math.min(pages.length - 1, pageIndex))].tab

  function firstPage(name) {
    for (var i = 0; i < pages.length; i++) if (pages[i].tab === name) return i
    return 0
  }

  // A swipe to another tab takes the keyboard's place in the body along.
  onTabChanged: if (root.zone === "body" && !root.searching) root.cursor = root.firstBodyStop().index

  // ---------------------------------------------------------- the keyboard
  //
  // One focus at a time, shown only after a key: zone "" (nothing focused,
  // as on opening and after any touch or click), "search" (the field),
  // "tabs" (the tabs, then Settings), "body" (tiles, rows), "footer" (the
  // session buttons) or "cancel". Tab walks every stop in reading order;
  // arrows move in two dimensions; Enter acts only on what is focused (or,
  // in a typed search, on the marked best match).

  // Body rows as lists of cursor indices, so Up and Down keep the column.
  readonly property var bodyRows: {
    var rows = []
    function chunk(start, count) {
      for (var i = 0; i < count; i += root.columns) {
        var row = []
        for (var j = i; j < Math.min(count, i + root.columns); j++) row.push(start + j)
        rows.push(row)
      }
    }
    if (root.searching) {
      if (root.query.trim()) {
        chunk(0, search.apps.length)
        for (var s = search.apps.length; s < resultRows.length; s++) rows.push([s])
      } else {
        for (var r = 0; r < recentRows.length; r++) rows.push([r])
      }
    } else if (root.tab === "apps") {
      chunk(0, appTileCount)
    } else if (root.tab === "actions") {
      var start = 0
      for (var g = 0; g < actionGroups.length; g++) {
        chunk(start, actionGroups[g].entries.length)
        start += actionGroups[g].entries.length
      }
    } else {
      chunk(0, sessionEntries.length)
    }
    return rows
  }

  readonly property int bodyCount: {
    var n = 0
    for (var r = 0; r < bodyRows.length; r++) n += bodyRows[r].length
    return n
  }

  readonly property int settingsStop: tabs.length
  readonly property bool hasFooter: !root.phone && !root.searching

  // Every stop, in the order Tab visits them.
  function focusStops() {
    var out = [{ zone: "search", index: 0 }]
    if (root.searching) {
      for (var r = 0; r < root.bodyCount; r++) out.push({ zone: "body", index: r })
      out.push({ zone: "cancel", index: 0 })
      return out
    }
    for (var t = 0; t < root.tabs.length; t++) out.push({ zone: "tabs", index: t })
    out.push({ zone: "tabs", index: root.settingsStop })
    for (var b = 0; b < root.bodyCount; b++) out.push({ zone: "body", index: b })
    if (root.hasFooter) for (var f = 0; f < root.sessionEntries.length; f++) out.push({ zone: "footer", index: f })
    return out
  }

  function keyFocus(zone, index) {
    return root.cursorShown && root.zone === zone && root.cursor === index
  }

  // The best match of a typed search, marked (no ring) while the keyboard
  // is not on a result: Enter runs it.
  function topMark(index) {
    return root.searching && !!root.query.trim() && root.zone !== "body" && index === root.topIndex
  }

  // Set by a key that sends focus into the field, so that focusing it from
  // the keyboard does not switch to the recents view the way a tap does.
  property bool keyboardIntoSearch: false

  function focusStop(stop) {
    root.cursorShown = true
    if (stop.zone === "search") {
      root.zone = "search"
      root.cursor = 0
      if (!searchField.activeFocus) {
        root.keyboardIntoSearch = true
        searchField.forceActiveFocus()
        root.keyboardIntoSearch = false
      }
      return
    }
    // Leaving the field: an empty search was only a place on the way.
    if (searchField.activeFocus) {
      keyCatcher.forceActiveFocus()
      if (root.searching && !root.query.trim()) {
        root.searching = false
        Qt.inputMethod.hide()
      }
    }
    root.zone = stop.zone
    root.cursor = stop.index
    root.revealCursor()
  }

  function tabStep(step) {
    var stops = root.focusStops()
    var at = -1
    if (root.zone !== "") {
      for (var i = 0; i < stops.length; i++)
        if (stops[i].zone === root.zone && stops[i].index === root.cursor) { at = i; break }
    }
    var next = at < 0 ? (step > 0 ? 0 : stops.length - 1) : (at + step + stops.length) % stops.length
    root.focusStop(stops[next])
  }

  // The first item of what is showing: the current page's first tile, or
  // the best match, or the first recent.
  function firstBodyStop() {
    if (root.searching) return { zone: "body", index: root.query.trim() ? root.topIndex : 0 }
    if (root.tab === "apps" && root.phone) return { zone: "body", index: root.pageIndex * root.perPage }
    return { zone: "body", index: 0 }
  }

  function moveCursor(dx, dy) {
    // The first arrow only shows where the keyboard is: the first item.
    if (root.zone === "" || (!root.cursorShown && root.zone !== "search")) {
      if (root.bodyCount > 0) root.focusStop(root.firstBodyStop())
      else root.focusStop({ zone: "search", index: 0 })
      return
    }
    root.cursorShown = true
    if (root.zone === "search") {
      if (dy > 0) {
        if (root.searching && root.bodyCount > 0) root.focusStop(root.firstBodyStop())
        else if (!root.searching) root.focusStop({ zone: "tabs", index: root.tabs.indexOf(root.tab) })
      }
      return
    }
    if (root.zone === "cancel") {
      if (dx < 0 || dy < 0) root.focusStop({ zone: "search", index: 0 })
      else if (dy > 0 && root.bodyCount > 0) root.focusStop(root.firstBodyStop())
      return
    }
    if (root.zone === "tabs") {
      if (dx !== 0) {
        // The tabs are buttons like Settings beside them: arrows and Tab
        // move between them, Enter or Space switches.
        root.cursor = Math.max(0, Math.min(root.settingsStop, root.cursor + dx))
      } else if (dy < 0) {
        root.focusStop({ zone: "search", index: 0 })
      } else if (dy > 0 && root.bodyCount > 0) {
        root.focusStop(root.firstBodyStop())
      }
      return
    }
    if (root.zone === "footer") {
      if (dx !== 0) root.cursor = Math.max(0, Math.min(sessionEntries.length - 1, root.cursor + dx))
      else if (dy < 0 && bodyRows.length > 0) root.focusStop({ zone: "body", index: bodyRows[bodyRows.length - 1][0] })
      return
    }
    var rows = bodyRows
    var rowAt = 0, colAt = 0
    for (var r = 0; r < rows.length; r++) {
      var c = rows[r].indexOf(root.cursor)
      if (c >= 0) { rowAt = r; colAt = c; break }
    }
    if (dx !== 0) {
      var last = rows[rows.length - 1]
      root.cursor = Math.max(0, Math.min(last[last.length - 1], root.cursor + dx))
    } else if (dy < 0) {
      if (rowAt === 0) {
        if (root.searching) root.focusStop({ zone: "search", index: 0 })
        else root.focusStop({ zone: "tabs", index: root.tabs.indexOf(root.tab) })
        return
      }
      var up = rows[rowAt - 1]
      root.cursor = up[Math.min(colAt, up.length - 1)]
    } else if (dy > 0) {
      if (rowAt === rows.length - 1) {
        if (root.hasFooter && sessionEntries.length > 0) root.focusStop({ zone: "footer", index: 0 })
        return
      }
      var down = rows[rowAt + 1]
      root.cursor = down[Math.min(colAt, down.length - 1)]
    }
    root.revealCursor()
  }

  // A touch or click anywhere: the pointer is in charge again, and the
  // keyboard's highlight goes.
  function pointerUsed() {
    root.menuKeys = false
    root.cursorShown = false
    root.zone = searchField.activeFocus ? "search" : ""
  }

  property var appGridView: null

  // A swipe between tabs or a scroll is under way.
  function scrolling() {
    return pager.dragging || pager.flicking || pager.moving || snap.running
      || (root.appGridView && root.appGridView.moving)
      || resultsFlick.moving || recentFlick.moving
  }

  function revealCursor() {
    if (root.zone !== "body" || root.searching || root.tab !== "apps") return
    if (root.phone) root.pageIndex = Math.floor(root.cursor / root.perPage)
    else if (root.appGridView) root.appGridView.positionViewAtIndex(root.cursor, GridView.Contain)
  }

  function activateCursor() {
    if (root.zone === "" || root.zone === "search") {
      // Nothing chosen: only a typed search has something to run, its
      // marked best match.
      if (root.searching && root.query.trim()) root.runRow(resultRows[root.topIndex])
      return
    }
    if (!root.cursorShown) return
    if (root.zone === "cancel") { root.endSearch(); return }
    if (root.zone === "tabs") {
      if (root.cursor < root.tabs.length) root.pageIndex = root.firstPage(root.tabs[root.cursor])
      else root.openSettings()
      return
    }
    if (root.zone === "footer") {
      root.runEntry(sessionEntries[root.cursor])
      return
    }
    if (root.searching) {
      var rows = root.query.trim() ? resultRows : recentRows
      root.runRow(rows[root.cursor])
    } else if (root.tab === "apps") {
      if (root.cursor < apps.length) root.launch(apps[root.cursor])
      else if (root.showsAddApps) root.openMenu("install")
    } else if (root.tab === "actions") {
      var flat = []
      for (var g = 0; g < actionGroups.length; g++) flat = flat.concat(actionGroups[g].entries)
      root.runEntry(flat[root.cursor])
    } else {
      root.runEntry(sessionEntries[root.cursor])
    }
  }

  // ------------------------------------------------------------- lifecycle

  // The GPU desktop fades the launcher in over the screen; the software one
  // shows it at once.
  readonly property bool gpu: Quickshell.env("QT_QUICK_BACKEND") !== "software"
  // 0 closed, 1 open; the surface stays mapped while it falls back to 0.
  property real reveal: 0
  // 0 browsing the tabs, 1 searching: the two views crossfade on it.
  property real searchMix: searching ? 1 : 0
  Behavior on searchMix {
    enabled: root.gpu && root.opened
    NumberAnimation { duration: Style.duration(180); easing.type: Easing.OutCubic }
  }
  // The wallpaper the desktop shows (a video one leaves the plain colour).
  property string wallpaper: ""

  Process {
    id: wallpaperProc
    command: ["readlink", "-f", (Quickshell.env("HOME") || "") + "/.local/state/omarchy/current/background"]
    stdout: StdioCollector {
      onStreamFinished: {
        var path = text.trim()
        root.wallpaper = path && !Util.isVideoPath(path) ? path : ""
      }
    }
  }

  Component.onCompleted: wallpaperProc.running = true

  // The background plugin names the new wallpaper the moment a theme or
  // background switch sets it, before its own fade: the blurred copy is made
  // then, not when the launcher next opens.
  readonly property var backgroundService: root.shell && root.shell.bootIntro ? root.shell.bootIntro.backgroundService : null
  readonly property string shownWallpaper: backgroundService ? String(backgroundService.currentBackground || "") : ""
  onShownWallpaperChanged: if (shownWallpaper) root.wallpaper = Util.isVideoPath(shownWallpaper) ? "" : shownWallpaper

  // The frosted background: one file per wallpaper, theme colour and
  // orientation, in the runtime directory. Both orientations are made
  // together, so turning the iPad only switches between two ready images.
  readonly property var backdropScreen: panel.screen || (Quickshell.screens.length > 0 ? Quickshell.screens[0] : null)
  readonly property real backdropScale: backdropScreen ? backdropScreen.devicePixelRatio : 1
  readonly property int backdropWidth: backdropScreen ? Math.round(backdropScreen.width * backdropScale) : 0
  readonly property int backdropHeight: backdropScreen ? Math.round(backdropScreen.height * backdropScale) : 0
  // How much of the theme's menu background lies over the blurred wallpaper.
  readonly property real backdropTint: 0.8
  readonly property color backdropColor: Commons.Color.menu.background
  // Everything but the size: what makes a background outdated.
  readonly property string backdropLook: wallpaper
    ? ["frosted4", wallpaper, Math.round(backdropColor.r * 255), Math.round(backdropColor.g * 255), Math.round(backdropColor.b * 255), backdropTint].join("|") : ""
  readonly property string backdropKey: backdropKeyFor(backdropWidth, backdropHeight)
  readonly property string backdropPath: backdropPathFor(backdropKey)
  // key -> path of the backgrounds made so far
  property var backdropSaved: ({})
  property var backdropQueue: []
  readonly property bool backdropReady: backdropKey !== "" && !!backdropSaved[backdropKey]

  function backdropKeyFor(width, height) {
    return root.backdropLook && width > 0 && height > 0 ? root.backdropLook + "|" + width + "x" + height : ""
  }

  function backdropPathFor(key) {
    return (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/omarchy-launcher-backdrop-" + Qt.md5(key) + ".png"
  }

  // The orientation on screen first, then the other one.
  onBackdropKeyChanged: {
    if (!root.backdropKey) return
    var wanted = [root.backdropKey, root.backdropKeyFor(root.backdropHeight, root.backdropWidth)]
    root.backdropQueue = wanted.filter(function(key) { return key && !root.backdropSaved[key] })
    if (!backdropProc.running) root.makeNextBackdrop()
  }

  function makeNextBackdrop() {
    if (root.backdropQueue.length === 0) return
    var key = root.backdropQueue[0]
    root.backdropQueue = root.backdropQueue.slice(1)
    var size = key.substring(key.lastIndexOf("|") + 1).split("x")
    var look = key.split("|")
    backdropProc.key = key
    backdropProc.command = [Quickshell.env("OMARCHY_PATH") + "/bin/omarchy-launcher-backdrop", root.wallpaper,
      root.backdropPathFor(key), size[0], size[1], look[2], look[3], look[4], look[5]]
    backdropProc.running = true
  }

  Process {
    id: backdropProc
    property string key: ""
    onExited: function(exitCode) {
      if (exitCode === 0) {
        var saved = ({})
        for (var k in root.backdropSaved) {
          // A background of an earlier wallpaper or theme colour is not
          // needed again; both orientations of the current one are.
          if (k.indexOf(root.backdropLook + "|") === 0) saved[k] = root.backdropSaved[k]
          else Quickshell.execDetached(["rm", "-f", root.backdropSaved[k]])
        }
        if (key.indexOf(root.backdropLook + "|") === 0) saved[key] = root.backdropPathFor(key)
        else Quickshell.execDetached(["rm", "-f", root.backdropPathFor(key)])
        root.backdropSaved = saved
      }
      Qt.callLater(root.makeNextBackdrop)
    }
  }

  property bool mapped: false
  NumberAnimation {
    id: revealIn
    target: root
    property: "reveal"
    to: 1
    duration: root.gpu ? Style.duration(200) : 0
    easing.type: Easing.OutCubic
  }

  NumberAnimation {
    id: revealOut
    target: root
    property: "reveal"
    to: 0
    duration: root.gpu ? Style.duration(120) : 0
    easing.type: Easing.InCubic
    onFinished: if (!root.opened) root.mapped = false
  }

  function open() {
    // A bar popup, or the control center, goes first: the launcher is never
    // shown over one.
    var bar = root.shell ? root.shell.bar : null
    if (bar && bar.activePopout && typeof bar.activePopout.close === "function") bar.activePopout.close()
    if (root.shell && root.shell.controlCenter && root.shell.controlCenter.opened) root.shell.controlCenter.close()
    if (root.appLibrary) root.appLibrary.refreshIcons()
    if (root.appsStale || root.apps.length === 0) root.rebuild()
    // Stop Screenrecording and the session list follow what is true now.
    if (root.menu) root.menu.evaluateGuards()
    // A wallpaper changed since: the next open shows it.
    wallpaperProc.running = true
    root.endSearch()
    root.pageIndex = 0
    root.zone = ""
    root.cursor = 0
    root.cursorShown = false
    root.menuEntry = null
    root.uninstallEntry = null
    root.now = Date.now()
    if (root.appGridView) root.appGridView.positionViewAtBeginning()
    revealOut.stop()
    root.opened = true
    if (root.mapped && panel.contentRevealed) revealIn.restart()
    root.mapped = true
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    if (!root.opened) return
    root.opened = false
    root.menuEntry = null
    root.uninstallEntry = null
    if (root.searching) Qt.inputMethod.hide()
    revealIn.stop()
    revealOut.restart()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  // A bar item's popup opening puts the launcher away.
  Connections {
    target: root.shell ? root.shell.bar : null
    function onActivePopoutChanged() {
      if (root.opened && root.shell.bar.activePopout) root.close()
    }
  }

  function rebuild() {
    root.appsStale = false
    var rows = root.appLibrary ? root.appLibrary.sortedEntries("") : []
    root.apps = rows.map(function(row) { return row.entry })
  }

  function showTab(name) {
    root.pageIndex = root.firstPage(name)
  }

  // The field took focus. A tap shows the recents at once; focus that the
  // keyboard moved there waits for typing.
  function fieldFocused() {
    root.zone = "search"
    root.cursor = 0
    if (!root.keyboardIntoSearch) root.beginSearch()
  }

  function beginSearch() {
    if (root.searching) return
    root.searching = true
    root.now = Date.now()
    recentFilesProc.running = true
  }

  // Cancel, Escape, or a tap beside an empty search: back to the tabs.
  function endSearch() {
    if (root.searching) Qt.inputMethod.hide()
    root.searching = false
    root.query = ""
    searchField.text = ""
    root.zone = ""
    root.cursor = 0
    keyCatcher.forceActiveFocus()
  }

  // A tap on empty space puts the search field away: with nothing typed,
  // search ends; with a query, its results stay and the keyboard goes.
  function backgroundTap() {
    if (root.menuEntry) {
      var shown = appMenu.visible
      root.menuEntry = null
      if (shown) return
    }
    if (!root.searching) return
    if (root.query.trim()) {
      keyCatcher.forceActiveFocus()
      Qt.inputMethod.hide()
      root.zone = ""
    } else {
      root.endSearch()
    }
  }

  function setQuery(text) {
    root.query = text
    // Typing is searching, however the field got its focus; the keyboard
    // stays in the field, the best match marked below it.
    if (text.trim()) root.beginSearch()
    if (root.zone === "body") { root.zone = "search"; root.cursor = 0 }
    // Providers (fonts, languages, kernels) fill their submenus on demand;
    // a search wants them all, as the menu's own search does.
    if (text.trim() && root.menu) root.menu.loadProvidersForSearch()
  }



  // ---------------------------------------------------------------- actions

  function launch(app) {
    if (!app || !root.appLibrary) return
    root.close()
    if (root.dock) root.dock.launchEntry(app)
    else root.appLibrary.launch(app.id, root.appLibrary.entryName(app))
  }

  // An entry runs as the menu runs it; a submenu opens in the menu (the
  // Settings window will take those over).
  function runEntry(e) {
    if (!e || root.isOff(e)) return
    if (e.kind === "menu" || e.kind === "link") {
      root.openMenu(e.kind === "link" ? e.target : e.id)
      return
    }
    root.close()
    if (root.menu) root.menu.runAction(e.action)
  }

  function runRow(row) {
    if (!row) return
    if (row.kind === "app") root.launch(row.app)
    else if (row.kind === "menu") root.runEntry(row.entry)
    else if (row.kind === "file") {
      root.close()
      Quickshell.execDetached(["xdg-open", row.file.path])
    }
  }

  function openMenu(id) {
    root.close()
    if (root.shell) root.shell.summon("omarchy.menu", JSON.stringify({ menu: id }))
  }

  // Until the Settings window exists, Settings is the Omarchy menu.
  function openSettings() {
    root.openMenu("root")
  }

  function ageText(time) {
    var a = Model.age(time, root.now)
    if (a[0] === "now") return Commons.I18n.t("launcher.justNow")
    var n = Commons.I18n.formatNumber(a[1])
    if (a[0] === "min") return Commons.I18n.tn("launcher.minutesAgo", a[1]).arg(n)
    if (a[0] === "h") return Commons.I18n.tn("launcher.hoursAgo", a[1]).arg(n)
    return Commons.I18n.tn("launcher.daysAgo", a[1]).arg(n)
  }

  // ------------------------------------------------------------- app menu

  // The tile or row a menu was opened from, lifted above the dimmed
  // launcher beside its menu: { kind: "tile" | "row", rect, row }.
  property var menuSource: null

  // The menu from the keyboard: Menu, Shift+F10 or Ctrl+Enter on the app
  // the keyboard is on. Its entries then take Up, Down, Tab, Enter, Space;
  // Escape returns to the app.
  property bool menuKeys: false
  property int menuCursor: 0
  property var keyedItem: null
  property var keyedApp: null
  property var keyedRow: null

  function openKeyedMenu() {
    if (!root.cursorShown || root.zone !== "body" || !root.keyedItem || !root.keyedApp || !root.keyedItem.keyed) return
    var item = root.keyedItem
    root.openAppMenu(root.keyedApp, item.mapToItem(panel.contentItem, item.width / 2, item.height / 2), item, root.keyedRow)
    root.menuKeys = true
    root.menuCursor = 0
  }

  function triggerMenuEntry(e) {
    if (!e) return
    var app = appMenu.app
    if (e.kind === "action") {
      root.close()
      e.action.execute()
    } else if (e.kind === "default") {
      root.menuEntry = null
      if (root.menu) {
        root.menu.runAction(e.entry.action)
        guardRefresh.restart()
      }
    } else if (e.kind === "dock") {
      if (root.dock && app) root.dock.setPinned(String(app.id || ""), !appMenu.pinned)
      root.menuEntry = null
    } else if (e.kind === "uninstall") {
      uninstallConfirm.selectedIndex = 1
      root.uninstallEntry = app
      root.menuEntry = null
    }
  }

  function openAppMenu(app, point, source, row) {
    root.menuKeys = false
    root.menuCursor = 0
    root.menuRemovable = false
    root.menuSource = source
      ? { kind: row ? "row" : "tile", rect: source.mapToItem(panel.contentItem, 0, 0, source.width, source.height), row: row || null }
      : null
    root.menuEntry = app
    // Beside the tile or row, from its top right, so the app stays visible
    // next to its menu; at the pointer when there is no source.
    root.menuPoint = root.menuSource
      ? Qt.point(root.menuSource.rect.x + root.menuSource.rect.width - Style.space(6), root.menuSource.rect.y + Style.space(6))
      : point
    removableProc.running = false
    removableProc.command = ["bash", "-c", removableScript, "bash", String(app.id || "")]
    removableProc.running = true
  }

  // The Setup › Defaults rows that name this app, e.g. Firefox under
  // Default Browser, with the menu's ✓ for the current default.
  function defaultRowsFor(app) {
    var m = root.menu
    if (!m || !m.items || !app) return []
    var guards = m.checkedResults
    var name = String(root.appLibrary ? root.appLibrary.entryName(app) : "").toLowerCase()
    var id = String(app.id || "").toLowerCase().replace(/\.desktop$/, "")
    var out = []
    for (var i = 0; i < m.itemOrder.length; i++) {
      var e = m.items[m.itemOrder[i]]
      if (!e || e.kind !== "action") continue
      var kind = m.items[e.parent]
      if (!kind || kind.parent !== "setup.default" || !root.shown(e) || !root.ancestorsShown(e)) continue
      var leaf = e.id.substring(e.id.lastIndexOf(".") + 1)
      if (e.label.toLowerCase() !== name && leaf !== id) continue
      out.push({ entry: e, label: kind.title || kind.label, checked: !!(m.checkedResults && m.checkedResults[e.id]) })
    }
    return out
  }

  // Whether an app may be uninstalled from here: not when its desktop file
  // comes from omarchy-a itself or a package omarchy-a depends on.
  readonly property string removableScript: '
id=${1%.desktop}.desktop
IFS=: read -ra dirs <<<"${XDG_DATA_HOME:-$HOME/.local/share}:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
file=""
for dir in "${dirs[@]}"; do [[ -f $dir/applications/$id ]] && { file=$dir/applications/$id; break; }; done
[[ -n $file ]] || { echo kept; exit; }
pkg=$(pacman -Qqo "$file" 2>/dev/null | head -1)
[[ -n $pkg ]] || { echo removable; exit; }
[[ $pkg != omarchy-a ]] || { echo kept; exit; }
LC_ALL=C pacman -Qi omarchy-a 2>/dev/null | awk \'/^Depends On/ { on = 1 } /^Optional Deps/ { on = 0 } on { sub(/^Depends On *: /, ""); print }\' \\
  | tr -s " " "\\n" | sed "s/[<>=].*//" | grep -qxF -- "$pkg" && echo kept || echo removable
'

  Process {
    id: removableProc
    stdout: StdioCollector {
      onStreamFinished: {
        root.menuRemovable = text.trim() === "removable"
        // Nothing to offer after all: no menu is left pending.
        if (root.menuEntry && appMenu.entries.length === 0) root.menuEntry = null
      }
    }
  }

  Process {
    id: recentFilesProc
    command: ["bash", "-lc", 'exec "$@"', "bash", Quickshell.env("OMARCHY_PATH") + "/bin/omarchy-launcher-recent-files", "6"]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var parsed = JSON.parse(text)
          root.recentFiles = Array.isArray(parsed) ? parsed : []
        } catch (e) {
          root.recentFiles = []
        }
      }
    }
  }

  Connections {
    target: root.appLibrary
    function onAppsChanged() {
      if (root.opened) root.rebuild()
      else root.appsStale = true
    }
    function onRemovalNeedsTerminal() {
      if (root.opened) root.close()
    }
  }

  // ----------------------------------------------------------------- window

  OverlayWindow {
    id: panel
    shown: root.mapped
    WlrLayershell.namespace: "omarchy-dock-apps"

    // The entrance starts once the surface shows at its real size.
    onContentRevealedChanged: if (contentRevealed && root.opened) {
      root.reveal = 0
      revealIn.restart()
      // The surface now has the keyboard: typing goes to search, arrows move.
      if (!searchField.activeFocus) keyCatcher.forceActiveFocus()
    }

    // The launcher's own background, below the bar: the wallpaper with the
    // theme's background colour almost opaque over it. The whole of it fades
    // in over whatever the screen shows, which keeps running beneath.
    Item {
      id: backdrop
      y: root.barInset
      width: parent.width
      height: Math.max(0, parent.height - y)
      clip: true
      opacity: root.reveal

      Rectangle {
        anchors.fill: parent
        color: Commons.Color.menu.background
      }

      // The wallpaper as tinted frosted glass, made ahead of time by
      // omarchy-launcher-backdrop at the panel's own pixel size, the theme's
      // colour already in it: shown 1:1, nothing scaled or blended here.
      Image {
        y: -root.barInset
        width: panel.width
        height: panel.height
        visible: root.backdropReady
        source: root.backdropReady ? Util.fileUrl(root.backdropPath) : ""
        asynchronous: false
        cache: false
        smooth: false
      }
    }

    // The bar is not dimmed, so it stays the bar: its strip is outside
    // the launcher's input, and a click there reaches the bar's own item (a
    // popup it opens puts the launcher away, see below).
    mask: Region { item: launcherInput }
    Item {
      id: launcherInput
      y: root.barInset
      width: parent.width
      height: Math.max(0, parent.height - root.barInset)
    }

    // Anywhere else that nothing takes: put search away, never close.
    MouseArea {
      y: root.barInset
      width: parent.width
      height: Math.max(0, parent.height - y)
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      onClicked: root.backgroundTap()
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true

      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (root.uninstallEntry) {
          if (uninstallConfirm.handleKey(event)) event.accepted = true
          return
        }
        var key = Util.readingKey(event)
        if (event.key === Qt.Key_Escape) {
          if (root.menuEntry && appMenu.visible) root.menuEntry = null
          else if (root.query) { searchField.text = ""; root.setQuery("") }
          else if (root.searching) root.endSearch()
          else if (searchField.activeFocus) { keyCatcher.forceActiveFocus(); root.zone = ""; root.cursorShown = false }
          else root.close()
        } else if (root.menuEntry && appMenu.visible) {
          var count = appMenu.entries.length
          var back = event.key === Qt.Key_Up || event.key === Qt.Key_Backtab
            || (event.key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier))
          if (event.key === Qt.Key_Down || event.key === Qt.Key_Up || event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
            // The first key only shows where the keyboard is.
            if (!root.menuKeys) root.menuCursor = back ? count - 1 : 0
            else root.menuCursor = (root.menuCursor + (back ? -1 : 1) + count) % count
            root.menuKeys = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
            if (root.menuKeys) root.triggerMenuEntry(appMenu.entries[root.menuCursor])
          } else {
            return
          }
        } else if (event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))
                   || ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier))) {
          root.openKeyedMenu()
        } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
          root.tabStep(event.key === Qt.Key_Backtab || (event.modifiers & Qt.ShiftModifier) ? -1 : 1)
        } else if (key === Qt.Key_Left) {
          // In the field the caret stays at the end; Left and Right are not
          // the keyboard's to move there.
          if (root.zone === "search") return
          root.moveCursor(-1, 0)
        } else if (key === Qt.Key_Right) {
          if (root.zone === "search") return
          root.moveCursor(1, 0)
        } else if (event.key === Qt.Key_Up) {
          root.moveCursor(0, -1)
        } else if (event.key === Qt.Key_Down) {
          root.moveCursor(0, 1)
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          root.activateCursor()
        } else if (event.key === Qt.Key_Space && !searchField.activeFocus && root.cursorShown && root.zone !== "") {
          // Space presses what the keyboard is on, as Enter does; in the
          // field (or with nothing focused) it is text.
          root.activateCursor()
        } else if (!searchField.activeFocus && event.text && event.text.charCodeAt(0) >= 32
                   && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
          // Typing on a physical keyboard goes straight into search.
          searchField.forceActiveFocus()
          searchField.text += event.text
        } else {
          return
        }
        event.accepted = true
      }
    }

    Item {
      id: content
      x: root.sideMargin
      y: root.barInset + (root.compact ? Style.space(8) : Style.space(root.phone ? 12 : 24))
      width: root.contentWidth
      height: parent.height - y - (root.compact ? Style.space(4) : Style.space(root.phone ? 16 : 24))
      opacity: root.reveal
      transform: [
        Scale {
          origin.x: content.width / 2
          origin.y: 0
          // Comes in settling from just over its size (and goes the same way).
          xScale: 1.03 - 0.03 * root.reveal
          yScale: 1.03 - 0.03 * root.reveal
        },
        Translate { y: Style.space(10) * (1 - root.reveal) }
      ]

      // ------------------------------------------------------ search row
      // Beside the field: Cancel while searching, else Settings on a phone.
      readonly property int trailing: root.searching ? cancelButton.width : 0

      // Drawn as the shell's text fields are: [controls] fill and border
      // for its state, the theme's corner radius.
      BorderSurface {
        id: searchBox
        readonly property bool hot: searchHover.hovered
        // Only Cancel coming and going animates the field; the launcher's
        // own size (set as its window maps on open) takes effect at once.
        property real cancelShare: root.searching ? 1 : 0
        Behavior on cancelShare {
          enabled: root.gpu && root.opened
          NumberAnimation { duration: Style.duration(180); easing.type: Easing.OutCubic }
        }
        width: parent.width - searchBox.cancelShare * (cancelButton.width + Style.spacing.lg)
        height: root.searchHeight
        radius: Style.cornerRadius
        // Focus in the shipped [controls] mirrors hover, whose border is
        // fainter than idle's, so a focused field would read as less active
        // than an idle one. Unless the theme gives focus its own look, the
        // active field takes the theme's selected fill over the normal
        // border: clearly the strongest of the three.
        readonly property bool themedFocus: Style.focusFillAlpha !== Style.hoverFillAlpha
          || Style.focusBorderAlpha !== Style.hoverBorderAlpha
          || Style.focusColorToken !== Style.hoverColorToken
        readonly property bool active: searchField.activeFocus
        color: active && !themedFocus ? Style.selectedFillFor(root.text, Commons.Color.accent)
          : Style.controlFill(active, hot, root.text, Commons.Color.accent)
        borderSpec: Border.controlSpec(active ? (themedFocus ? "focus" : "normal") : (hot ? "hover-cursor" : "normal"), root.text, Commons.Color.accent)

        HoverHandler { id: searchHover; acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad }

        // The whole box is the field's target, not only its text line, and a
        // little past it where the field is shorter than a finger.
        MouseArea {
          anchors.fill: parent
          anchors.topMargin: -Math.max(0, (root.touchMin - parent.height) / 2)
          anchors.bottomMargin: -Math.max(0, (root.touchMin - parent.height) / 2)
          cursorShape: Qt.IBeamCursor
          onClicked: {
            searchField.forceActiveFocus()
            Qt.inputMethod.hide()
            Qt.inputMethod.show()
          }
        }

        Text {
          id: searchGlyph
          anchors.left: parent.left
          anchors.leftMargin: Style.space(16)
          anchors.verticalCenter: parent.verticalCenter
          text: ""
          color: root.faint
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.title
        }

        FilterInput {
          id: searchField
          focus: false
          anchors.left: searchGlyph.right
          anchors.leftMargin: Style.space(12)
          anchors.right: parent.right
          anchors.rightMargin: Style.space(16)
          anchors.verticalCenter: parent.verticalCenter
          keyHandler: keyCatcher
          color: root.text
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.heading
          onActiveFocusChanged: if (activeFocus) root.fieldFocused()
          onTextChanged: if (text !== root.query) root.setQuery(text)
        }

        // The caret, in the theme's accent: the sign of a field taking text.
        // FilterInput keeps Qt's own caret hidden (it is append-only).
        Rectangle {
          id: caret
          visible: searchField.activeFocus
          // Empty, it waits in the gap before the placeholder, which never
          // moves; with text, it follows the text.
          x: searchField.text === "" ? searchField.x - width - Style.space(3)
            : searchField.x + Math.min(searchField.contentWidth, searchField.width) + Style.space(1)
          anchors.verticalCenter: searchField.verticalCenter
          width: Math.max(2, Style.space(2))
          height: Math.round(searchField.font.pixelSize * 1.25)
          color: Commons.Color.accent

          SequentialAnimation on opacity {
            running: caret.visible && root.gpu
            loops: Animation.Infinite
            alwaysRunToEnd: false
            NumberAnimation { to: 1; duration: 0 }
            PauseAnimation { duration: 530 }
            NumberAnimation { to: 0; duration: 0 }
            PauseAnimation { duration: 530 }
          }
        }

        Text {
          anchors.fill: searchField
          visible: searchField.text === ""
          textFormat: Text.PlainText
          text: root.phone ? Commons.I18n.t("launcher.searchShort") : Commons.I18n.t("launcher.search")
          color: root.faint
          font: searchField.font
          verticalAlignment: Text.AlignVCenter
          elide: Text.ElideRight
        }
      }

      // Cancel ends search, as Escape does.
      Button {
        id: cancelButton
        opacity: root.searchMix
        visible: opacity > 0
        anchors.right: parent.right
        // As tall as a finger needs, centred on the field even where the
        // field is shorter.
        y: (root.searchHeight - height) / 2
        height: Math.max(root.touchMin, root.searchHeight)
        text: Commons.I18n.t("common.cancel")
        foreground: Commons.Color.accent
        fontFamily: Style.font.menuFamily
        fontSize: Style.font.subtitle
        selected: root.keyFocus("cancel", 0)
        onClicked: root.endSearch()
        FocusRing { visible: parent.selected }
      }

      // --------------------------------------------------------- tab row
      Item {
        id: tabRow
        opacity: 1 - root.searchMix
        visible: opacity > 0
        transform: Translate { y: -Style.space(6) * root.searchMix }
        anchors.top: searchBox.bottom
        anchors.topMargin: root.compact ? Style.space(4) : Style.space(root.phone ? 10 : 16)
        width: parent.width
        height: Style.space(root.compact ? 30 : 36)

        Row {
          id: tabItems
          height: parent.height
          spacing: Style.space(root.phone ? 18 : 28)

          Repeater {
            id: tabRepeater
            model: root.tabs

            Item {
              id: tabItem
              required property string modelData
              required property int index
              readonly property bool active: root.tab === modelData
              readonly property bool focused: root.keyFocus("tabs", index)
              width: tabLabel.implicitWidth + (tabCount.visible ? tabCount.implicitWidth + Style.space(8) : 0)
              height: parent.height

              TabHighlight {
                pressed: tabMouse.pressed
                hovered: tabHover.hovered
                focused: tabItem.focused
              }
              HoverHandler { id: tabHover; acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad }

              Text {
                id: tabLabel
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: tabItem.modelData === "apps" ? (root.entry("apps") ? root.entry("apps").label : "")
                  : tabItem.modelData === "actions" ? Commons.I18n.t("launcher.actions")
                  : (root.entry("system") ? root.entry("system").label : "")
                color: tabItem.active || tabItem.focused ? root.text : root.faint
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.subtitle
                font.bold: tabItem.active
              }
              Text {
                id: tabCount
                visible: !root.phone && tabItem.modelData !== "system"
                anchors.left: tabLabel.right
                anchors.leftMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: Commons.I18n.formatNumber(tabItem.modelData === "apps" ? root.apps.length : root.actionCount)
                color: tabItem.active ? Commons.Color.accent : root.faint
                font.family: Style.font.menuFamily
                font.pixelSize: Style.font.caption
              }
              MouseArea {
                id: tabMouse
                anchors.fill: parent
                anchors.leftMargin: -Style.space(8)
                anchors.rightMargin: -Style.space(8)
                anchors.topMargin: -Math.max(Style.space(4), (root.touchMin - parent.height) / 2)
                anchors.bottomMargin: -Math.max(Style.space(4), (root.touchMin - parent.height) / 2)
                cursorShape: Qt.PointingHandCursor
                onClicked: root.showTab(tabItem.modelData)
              }
            }
          }
        }

        // The underline follows the finger between tabs while swiping.
        Rectangle {
          id: tabIndicator
          readonly property real f: pager.tabFloat
          readonly property int last: Math.max(0, tabRepeater.count - 1)
          readonly property Item from: tabRepeater.count > 0 ? tabRepeater.itemAt(Math.max(0, Math.min(last, Math.floor(f)))) : null
          readonly property Item to: tabRepeater.count > 0 ? tabRepeater.itemAt(Math.max(0, Math.min(last, Math.ceil(f)))) : null
          readonly property real t: f - Math.floor(f)
          anchors.bottom: parent.bottom
          x: from && to ? tabItems.x + from.x + (to.x - from.x) * t : 0
          width: from && to ? from.width + (to.width - from.width) * t : 0
          height: Style.space(2)
          color: Commons.Color.accent
          z: 1
        }

        // Settings at the end of the tab row on an iPad: the shell's button,
        // so it presses, hovers and takes the keyboard cursor as every
        // other button does.
        // Settings at the end of the tab row, a control like the tabs: the
        // same plain hover and press, the same ring for the keyboard. A
        // finger gets 44 points, more than the highlight shows.
        Item {
          id: settingsButton
          anchors.right: parent.right
          height: parent.height
          width: settingsRow.implicitWidth + Style.space(16)

          TabHighlight {
            anchors.leftMargin: 0
            anchors.rightMargin: 0
            pressed: settingsMouse.pressed
            hovered: settingsHover.hovered
            focused: root.keyFocus("tabs", root.settingsStop)
          }
          Row {
            id: settingsRow
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -Style.space(1)
            spacing: Style.space(6)
            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "\uf013"
              color: root.text
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.body
            }
            Text {
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: Commons.I18n.t("launcher.settings")
              color: root.text
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.subtitle
            }
          }
          HoverHandler { id: settingsHover; acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad }
          MouseArea {
            id: settingsMouse
            anchors.centerIn: parent
            width: parent.width
            height: Math.max(root.touchMin, parent.height)
            cursorShape: Qt.PointingHandCursor
            onClicked: root.openSettings()
          }
        }

        Rectangle {
          anchors.bottom: parent.bottom
          width: parent.width
          height: Math.max(1, Style.space(1))
          color: root.hairline
        }
      }

      // ------------------------------------------------------------ body
      Item {
        id: body
        anchors.top: searchBox.bottom
        anchors.topMargin: tabRow.anchors.topMargin
        anchors.bottom: parent.bottom
        width: parent.width
        // Room the session buttons take at the bottom while browsing.
        readonly property int footerSpace: !root.phone && root.sessionEntries.length > 0 ? footer.height + Style.space(16) : 0

        // The tabs' pages, side by side. The finger moves them 1:1; on
        // release they snap to a page, the next one when the swipe was
        // quick, with a short ease-out, as mobile tabs do.
        Flickable {
          id: pager
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.topMargin: tabRow.height + root.gap
          // The dots float over the bottom edge; app pages leave them room
          // in their row count, other pages use the full height.
          anchors.bottom: parent.bottom
          anchors.bottomMargin: body.footerSpace
          opacity: 1 - root.searchMix
          visible: opacity > 0
          transform: Translate { y: Style.space(10) * root.searchMix }
          clip: true
          contentWidth: width * root.pages.length
          contentHeight: height
          flickableDirection: Flickable.HorizontalFlick
          boundsBehavior: Flickable.StopAtBounds
          pressDelay: 0

          // Where the swipe is, in pages and in tabs (a phone's app pages
          // all belong to Apps).
          readonly property real pageFloat: width > 0 ? contentX / width : 0
          readonly property real tabFloat: Math.max(0, pageFloat - (root.appPageCount - 1))

          function snapTo(index) {
            index = Math.max(0, Math.min(root.pages.length - 1, index))
            snap.stop()
            snap.to = index * width
            snap.restart()
            if (root.pageIndex !== index) root.pageIndex = index
          }

          onDraggingChanged: {
            if (dragging) { snap.stop(); return }
            var velocity = horizontalVelocity
            cancelFlick()
            var target = Math.round(pageFloat)
            if (Math.abs(velocity) > Style.space(350))
              target = velocity > 0 ? Math.floor(pageFloat) + 1 : Math.ceil(pageFloat) - 1
            snapTo(target)
          }
          onWidthChanged: { snap.stop(); contentX = root.pageIndex * width }
          onContentWidthChanged: if (!dragging && !snap.running) contentX = Math.min(root.pageIndex, root.pages.length - 1) * width

          NumberAnimation {
            id: snap
            target: pager
            property: "contentX"
            duration: Style.duration(220)
            easing.type: Easing.OutCubic
          }

          Row {
            Repeater {
              model: root.pages
              Loader {
                required property var modelData
                required property int index
                width: pager.width
                height: pager.height
                sourceComponent: modelData.tab === "apps" ? (root.phone ? phoneAppsPage : padAppsPage) : groupsPage
                onLoaded: item.pageData = modelData
              }
            }
          }
        }

        Connections {
          target: root
          function onPageIndexChanged() {
            if (!pager.dragging && Math.round(pager.contentX) !== Math.round(root.pageIndex * pager.width)) pager.snapTo(root.pageIndex)
          }
        }

        Binding {
          target: root
          property: "pagerHeight"
          value: pager.height
        }

        // A phone's app pages, as dots.
        Item {
          id: dots
          anchors.bottom: parent.bottom
          anchors.bottomMargin: body.footerSpace
          width: parent.width
          height: root.dotsHeight
          opacity: 1 - root.searchMix
          z: 1

          Row {
            id: dotRow
            anchors.centerIn: parent
            visible: root.tab === "apps" && root.appPageCount > 1
            spacing: Style.space(6)
            Repeater {
              id: dotRepeater
              model: root.appPageCount
              Rectangle {
                required property int index
                anchors.verticalCenter: parent.verticalCenter
                width: index === root.pageIndex ? Style.space(18) : Style.space(6)
                height: Style.space(6)
                radius: Style.cornerRadius
                color: index === root.pageIndex ? Commons.Color.accent : root.faint
                scale: index === root.pageIndex && dotStrip.pressed ? 1.3 : 1
                Behavior on scale { enabled: root.gpu; NumberAnimation { duration: Style.duration(100); easing.type: Easing.OutCubic } }
              }
            }
          }

          // Dots are too small to aim at: the strip around them is one target
          // a finger can hit, as on iOS. Left of the current page's dot goes
          // back a page, right of it forward.
          MouseArea {
            id: dotStrip
            visible: dotRow.visible
            anchors.centerIn: dotRow
            width: dotRow.width + 2 * root.touchMin
            height: root.touchMin
            onClicked: function(event) {
              var current = dotRepeater.itemAt(root.pageIndex)
              if (!current) return
              var middle = dotRow.x + current.x + current.width / 2 - x
              if (event.x < middle) root.pageIndex = Math.max(0, root.pageIndex - 1)
              else root.pageIndex = Math.min(root.appPageCount - 1, root.pageIndex + 1)
            }
          }
        }

        // Search, nothing typed yet: recent apps and recent files, side by
        // side on an iPad, one under the other on a phone.
        Flickable {
          id: recentFlick
          anchors.fill: parent
          anchors.topMargin: Style.space(4)
          opacity: root.searchMix
          visible: opacity > 0 && !root.query.trim()
          transform: Translate { y: Style.space(10) * (1 - root.searchMix) }
          contentHeight: Math.max(recentGrid.height, height)
          boundsBehavior: Flickable.StopAtBounds
          clip: true

          MouseArea {
            width: recentFlick.width
            height: recentFlick.contentHeight
            onClicked: root.backgroundTap()
          }

          Grid {
            id: recentGrid
            width: parent.width
            columns: root.listColumns
            columnSpacing: Style.space(32)
            rowSpacing: Style.space(16)

            Repeater {
              model: 2
              Column {
                id: recentColumn
                required property int index
                width: root.phone ? body.width : (body.width - Style.space(32)) / 2
                readonly property var rows: index === 0 ? root.recentAppRows
                  : root.recentFiles.map(function(file) { return { kind: "file", file: file } })

                Heading {
                  // A title only tells sections apart: none for one alone.
                  visible: recentColumn.rows.length > 0 && root.recentAppRows.length > 0 && root.recentFiles.length > 0
                  text: recentColumn.index === 0 ? Commons.I18n.t("launcher.recentApps") : Commons.I18n.t("launcher.recentFiles")
                }
                Repeater {
                  model: recentColumn.rows
                  ResultRow {
                    required property var modelData
                    required property int index
                    width: recentColumn.width
                    row: modelData
                    cursorIndex: (recentColumn.index === 1 ? root.recentAppRows.length : 0) + index
                    showsTop: false
                  }
                }
              }
            }
          }
        }

        // Search results: matching apps across the top, then the menu's
        // matches in a grid of sections below.
        Flickable {
          id: resultsFlick
          anchors.fill: parent
          anchors.topMargin: Style.space(4)
          opacity: root.searchMix
          visible: opacity > 0 && !!root.query.trim()
          transform: Translate { y: Style.space(10) * (1 - root.searchMix) }
          contentHeight: Math.max(resultsColumn.height, height)
          boundsBehavior: Flickable.StopAtBounds
          clip: true

          MouseArea {
            width: resultsFlick.width
            height: resultsFlick.contentHeight
            onClicked: root.backgroundTap()
          }

          Column {
            id: resultsColumn
            width: resultsFlick.width
            spacing: Style.space(16)

            Column {
              visible: root.search.apps.length > 0
              width: parent.width

              Heading {
                visible: root.search.groups.length > 0
                text: root.entry("apps") ? root.entry("apps").label : ""
              }

              Grid {
                columns: root.columns
                Repeater {
                  model: root.search.apps
                  AppTile {
                    required property var modelData
                    required property int index
                    width: root.cellWidth
                    height: root.cellHeight
                    app: modelData.app
                    cursorIndex: index
                    inSearch: true
                  }
                }
              }
            }

            Grid {
              width: parent.width
              columns: root.listColumns
              columnSpacing: Style.space(32)
              rowSpacing: Style.space(16)

              Repeater {
                model: root.search.groups
                Column {
                  id: resultGroup
                  required property var modelData
                  width: root.phone ? resultsColumn.width : (resultsColumn.width - Style.space(32)) / 2

                  Heading {
                    visible: root.search.groups.length + (root.search.apps.length > 0 ? 1 : 0) > 1
                    text: resultGroup.modelData.label
                  }
                  Repeater {
                    model: resultGroup.modelData.rows
                    ResultRow {
                      required property var modelData
                      required property int index
                      width: resultGroup.width
                      row: modelData
                      cursorIndex: resultGroup.modelData.start + index
                      showsTop: true
                    }
                  }
                }
              }
            }
          }

          Text {
            visible: root.resultRows.length === 0
            anchors.horizontalCenter: parent.horizontalCenter
            y: Style.space(40)
            textFormat: Text.PlainText
            text: Commons.I18n.t("launcher.noResults").arg(root.query.trim())
            color: root.faint
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.title
          }
        }
      }

      // ---------------------------------------------- session footer (iPad)
      Row {
        id: footer
        opacity: 1 - root.searchMix
        visible: opacity > 0 && !root.phone && root.sessionEntries.length > 0
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.touchMin
        spacing: Style.space(6)
        layoutDirection: Qt.LeftToRight

        Repeater {
          model: root.sessionEntries
          // The shell's button: [controls] fills, borders and focus ring;
          // Shutdown in the theme's urgent colour.
          Button {
            required property var modelData
            required property int index
            height: footer.height
            bordered: true
            selected: root.keyFocus("footer", index)
            text: modelData.label
            iconText: modelData.icon
            foreground: modelData.id === "system.shutdown" ? Commons.Color.urgent : root.text
            fontFamily: Style.font.menuFamily
            fontSize: Style.font.bodySmall
            iconSize: Style.font.bodySmall
            onClicked: root.runEntry(modelData)
            FocusRing { visible: parent.selected }
          }
        }
      }
    }

    // ---------------------------------------------------- the app's menu

    // While it is open the rest of the launcher dims under the theme's menu
    // scrim, and a tap anywhere on it only closes the menu.
    Rectangle {
      anchors.fill: parent
      color: Commons.Color.menu.scrim
      opacity: appMenu.visible ? 1 : 0
      visible: opacity > 0
      Behavior on opacity {
        enabled: root.gpu
        NumberAnimation { duration: Style.duration(140); easing.type: Easing.OutCubic }
      }

      MouseArea {
        anchors.fill: parent
        enabled: appMenu.visible
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPressed: root.menuEntry = null
      }
    }

    // The app the menu belongs to stays lit above the scrim, where it was.
    Loader {
      active: appMenu.visible && !!root.menuSource
      x: root.menuSource ? root.menuSource.rect.x : 0
      y: root.menuSource ? root.menuSource.rect.y : 0
      width: root.menuSource ? root.menuSource.rect.width : 0
      height: root.menuSource ? root.menuSource.rect.height : 0
      sourceComponent: root.menuSource && root.menuSource.kind === "row" ? liftedRow : liftedTile
    }

    Component {
      id: liftedTile
      AppTile { app: root.menuEntry; enabled: false }
    }

    Component {
      id: liftedRow
      ResultRow { row: root.menuSource ? root.menuSource.row : null; enabled: false }
    }
    BorderSurface {
      id: appMenu

      readonly property var app: root.menuEntry
      readonly property var desktopActions: {
        var list = app && app.actions ? app.actions : []
        var out = []
        for (var i = 0; i < list.length; i++) out.push(list[i])
        return out
      }
      readonly property var defaults: root.defaultRowsFor(app)
      readonly property bool pinned: !!app && !!root.dock && root.dock.isPinned(String(app.id || ""))
      // Everything the menu offers, in order: the app's own actions, then
      // the defaults it can be, the dock, Uninstall. Touch and keyboard walk
      // the same list.
      readonly property var entries: {
        var out = []
        for (var i = 0; i < desktopActions.length; i++)
          out.push({ kind: "action", text: desktopActions[i].name, action: desktopActions[i] })
        var own = out.length
        for (var d = 0; d < defaults.length; d++)
          out.push({ kind: "default", text: defaults[d].label, checked: defaults[d].checked, entry: defaults[d].entry })
        if (root.dock)
          out.push({ kind: "dock", text: pinned ? Commons.I18n.t("dock.removeFromDock") : Commons.I18n.t("dock.keepInDock") })
        if (root.menuRemovable)
          out.push({ kind: "uninstall", text: Commons.I18n.t("dock.uninstall") })
        if (own > 0 && out.length > own) out[own].separatorAbove = true
        return out
      }

      // An app with nothing to offer (no actions, no default to set, nothing
      // to uninstall) gets no empty menu; Uninstall can arrive a moment later.
      visible: !!app && entries.length > 0
      width: Math.max(Style.space(240), appMenuColumn.implicitWidth) + padding * 2
      height: appMenuColumn.implicitHeight + padding * 2
      // Beside the app, on its right (its left in a right-to-left
      // language) or else the other side; where neither side has room (a
      // phone), below it, or above when it is near the bottom. The app and
      // its menu never cover each other.
      readonly property var source: root.menuSource ? root.menuSource.rect : null
      readonly property real overlap: Style.space(6)
      readonly property real rightX: source ? source.x + source.width - overlap : root.menuPoint.x
      readonly property real leftX: source ? source.x + overlap - width : root.menuPoint.x - width
      readonly property bool fitsRight: rightX + width + Style.gapsOut <= panel.width
      readonly property bool fitsLeft: leftX >= Style.gapsOut
      readonly property bool stacked: !!source && !fitsRight && !fitsLeft
      readonly property bool fitsBelow: !!source && source.y + source.height + height + Style.gapsOut <= panel.height
      x: stacked
        ? Math.max(Style.gapsOut, Math.min(panel.width - width - Style.gapsOut, source.x + source.width / 2 - width / 2))
        : (LayoutMirroring.enabled ? (fitsLeft ? leftX : rightX) : (fitsRight ? rightX : (fitsLeft ? leftX : Math.max(Style.gapsOut, leftX))))
      y: stacked
        ? (fitsBelow ? source.y + source.height - overlap : Math.max(Style.gapsOut, source.y - height + overlap))
        : Math.min(root.menuPoint.y, panel.height - height - Style.gapsOut)
      radius: Style.cornerRadius
      color: Commons.Color.popups.background
      borderSpec: Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Style.normalBorderWidth)
      padding: Style.spacing.sm

      MouseArea { anchors.fill: parent }

      Column {
        id: appMenuColumn
        x: appMenu.contentLeftInset
        y: appMenu.contentTopInset
        width: appMenu.width - appMenu.contentLeftInset - appMenu.contentRightInset

        Repeater {
          model: appMenu.entries
          Column {
            id: menuItem
            required property var modelData
            required property int index
            width: appMenuColumn.width

            Rectangle {
              visible: !!menuItem.modelData.separatorAbove
              width: parent.width
              height: visible ? Math.max(1, Style.space(1)) : 0
              color: root.hairline
            }
            MenuRow {
              text: menuItem.modelData.text
              checked: !!menuItem.modelData.checked
              keyed: root.menuKeys && root.menuCursor === menuItem.index
              onTriggered: root.triggerMenuEntry(menuItem.modelData)
            }
          }
        }
      }
    }

    ConfirmDialog {
      id: uninstallConfirm
      anchors.fill: parent
      opened: !!root.uninstallEntry
      z: 10
      message: Commons.I18n.t("common.uninstallConfirm").arg(root.uninstallEntry && root.appLibrary ? root.appLibrary.entryName(root.uninstallEntry) : "")
      confirmText: Commons.I18n.t("common.uninstall")
      background: Commons.Color.menu.background
      foreground: Commons.Color.menu.text
      scrim: Commons.Color.menu.scrim
      selectedBackground: Commons.Color.menu.selectedBackground
      selectedText: Commons.Color.menu.selectedText
      fontFamily: Style.font.menuFamily
      cornerRadius: Style.cornerRadius
      onCanceled: { root.uninstallEntry = null; keyCatcher.forceActiveFocus() }
      onConfirmed: {
        var app = root.uninstallEntry
        root.uninstallEntry = null
        keyCatcher.forceActiveFocus()
        if (app && root.appLibrary) {
          recentAppStamps.forget(String(app.id || ""))
          root.appLibrary.remove(app.id, root.appLibrary.entryName(app))
        }
      }
    }

    // Any touch or click, wherever it lands: the pointer is in charge, the
    // keyboard's highlight goes. It only watches; what is under it still
    // gets the press.
    Item {
      anchors.fill: parent
      z: 1000
      PointHandler {
        acceptedDevices: PointerDevice.AllDevices
        onActiveChanged: if (active) root.pointerUsed()
      }
    }
  }

  // A default just picked shows its ✓ once the menu has asked again.
  Timer {
    id: guardRefresh
    interval: 600
    onTriggered: if (root.menu) root.menu.evaluateGuards()
  }

  // --------------------------------------------------------------- pieces

  // An app's icon and name: tap to open, long-press or right-click for its
  // menu. In search the best match is marked before a key moves.
  component AppTile: Item {
    id: cell
    property var app: null
    property int cursorIndex: -1
    property bool inSearch: false
    readonly property bool keyed: inSearch === root.searching && root.keyFocus("body", cursorIndex)
    readonly property bool focused: keyed || (inSearch && root.topMark(cursorIndex))
    onKeyedChanged: if (keyed) { root.keyedItem = cell; root.keyedApp = cell.app; root.keyedRow = null }

    readonly property bool pressed: cellMouse.pressed && !cellMouse.travelled

    CellHighlight {
      focused: cell.focused
      ringed: cell.keyed
      hovered: cellHover.hovered
      pressed: cell.pressed
    }

    PressScale {
      id: cellSqueeze
      pressed: cell.pressed
      holds: true
    }

    Image {
      id: appIcon
      scale: cellSqueeze.value
      anchors.horizontalCenter: parent.horizontalCenter
      y: Style.space(10)
      width: root.iconSize
      height: root.iconSize
      sourceSize: Qt.size(root.iconSize * 2, root.iconSize * 2)
      source: cell.app && root.appLibrary ? root.appLibrary.iconSource(cell.app.icon) : ""
      fillMode: Image.PreserveAspectFit
      asynchronous: false
      smooth: true
      mipmap: true
    }

    Text {
      anchors.top: appIcon.bottom
      anchors.topMargin: Style.spacing.md
      anchors.horizontalCenter: parent.horizontalCenter
      width: parent.width - Style.space(8)
      textFormat: Text.PlainText
      text: cell.app && root.appLibrary ? root.appLibrary.entryName(cell.app) : ""
      color: cell.focused ? Commons.Color.menu.selectedText : root.text
      font.family: Style.font.menuFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.Wrap
      maximumLineCount: root.labelLines
      elide: Text.ElideRight
    }

    // A pointer that hovers; a finger leaves no highlight behind.
    HoverHandler { id: cellHover; acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad }
    MouseArea {
      id: cellMouse
      // A press that travels is a swipe or a scroll, never a long press.
      property point pressedAt
      property bool travelled: false
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      onPressed: function(event) { travelled = false; pressedAt = Qt.point(event.x, event.y) }
      onPositionChanged: function(event) {
        if (Math.hypot(event.x - pressedAt.x, event.y - pressedAt.y) > Qt.styleHints.startDragDistance) travelled = true
      }
      onCanceled: travelled = true
      onPressAndHold: function(event) {
        if (travelled || !cell.app || root.scrolling()) return
        cellSqueeze.release()
        root.openAppMenu(cell.app, cell.mapToItem(panel.contentItem, event.x, event.y), cell)
      }
      onClicked: function(event) {
        if (!cell.app || travelled) return
        if (event.button === Qt.RightButton) {
          root.openAppMenu(cell.app, cell.mapToItem(panel.contentItem, event.x, event.y), cell)
          return
        }
        if (root.menuEntry) {
          var shown = appMenu.visible
          root.menuEntry = null
          if (shown) return
        }
        root.launch(cell.app)
      }
    }
  }

  // The last tile on an iPad: the menu's Install list.
  component AddAppsTile: Item {
    id: addCell
    property int cursorIndex: -1
    readonly property bool focused: !root.searching && root.keyFocus("body", cursorIndex)

    CellHighlight {
      focused: addCell.focused
      hovered: addHover.hovered
      pressed: addMouse.pressed
    }

    PressScale {
      id: addSqueeze
      pressed: addMouse.pressed
    }
    Rectangle {
      id: addBox
      scale: addSqueeze.value
      anchors.horizontalCenter: parent.horizontalCenter
      y: Style.space(10)
      width: root.iconSize
      height: root.iconSize
      color: "transparent"
      radius: Style.cornerRadius
      border.width: Style.normalBorderWidth
      border.color: Style.normalBorderColor
      Text {
        anchors.centerIn: parent
        text: "+"
        color: root.faint
        font.family: Style.font.menuFamily
        font.pixelSize: Math.round(root.iconSize * 0.45)
      }
    }
    Text {
      anchors.top: addBox.bottom
      anchors.topMargin: Style.spacing.md
      anchors.horizontalCenter: parent.horizontalCenter
      width: parent.width - Style.space(8)
      textFormat: Text.PlainText
      text: Commons.I18n.t("launcher.addApps")
      color: root.faint
      font.family: Style.font.menuFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
      elide: Text.ElideRight
    }
    HoverHandler { id: addHover; acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad }
    MouseArea {
      id: addMouse
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: root.openMenu("install")
    }
  }

  // A group's title: the shell's section header, as its panels use it.
  component Heading: PanelSectionHeader {
    width: parent ? parent.width : 0
    foreground: root.text
    fontFamily: Style.font.menuFamily
    bottomPadding: Style.spacing.lg
    // The launcher's groups read as small capitals, as in its design.
    font.capitalization: Font.AllUppercase
    font.letterSpacing: Style.space(1.5)
  }

  // Behind a tab or Settings: hover and press fills (instant, as on the
  // tiles), the keyboard's ring; the rectangle a focused tab has always had.
  component TabHighlight: BorderSurface {
    property bool pressed: false
    property bool hovered: false
    property bool focused: false
    anchors.fill: parent
    anchors.leftMargin: -Style.space(8)
    anchors.rightMargin: -Style.space(8)
    anchors.topMargin: Style.space(2)
    anchors.bottomMargin: Style.space(4)
    radius: Style.cornerRadius
    color: pressed ? Style.pressedFillFor(root.text, Commons.Color.accent)
      : (focused ? Commons.Color.menu.selectedBackground : (hovered ? Style.hoverFill : "transparent"))
    borderSpec: focused ? root.focusRing : Border.none()
  }

  // The keyboard's ring, laid over a shell button that the cursor is on.
  component FocusRing: BorderSurface {
    anchors.fill: parent
    radius: Style.cornerRadius
    color: "transparent"
    borderSpec: root.focusRing
  }

  // How a tile's icon answers a finger: squeezed at once on touch-down, a
  // little further while a long press builds up (so the menu is seen
  // coming), sprung back on release. The software desktop shows the fill
  // alone.
  component PressScale: Item {
    id: squeeze
    property bool pressed: false
    property bool holds: false
    property real value: 1
    visible: false

    onPressedChanged: {
      if (!root.gpu) return
      if (pressed) { out.stop(); press.restart() }
      else release()
    }
    function release() {
      press.stop()
      out.restart()
    }

    SequentialAnimation {
      id: press
      NumberAnimation { target: squeeze; property: "value"; to: 0.92; duration: Style.duration(80); easing.type: Easing.OutCubic }
      NumberAnimation {
        target: squeeze; property: "value"
        to: squeeze.holds ? 0.88 : 0.92
        duration: squeeze.holds ? Style.duration(Math.max(0, Qt.styleHints.mousePressAndHoldInterval - 80)) : 0
      }
    }
    NumberAnimation { id: out; target: squeeze; property: "value"; to: 1; duration: Style.duration(160); easing.type: Easing.OutBack }
  }

  // Behind a tile: the menu's selection for the keyboard cursor (as the
  // Omarchy menu marks its row), the hover fill for a pointer.
  component CellHighlight: BorderSurface {
    property bool focused: false
    property bool ringed: focused
    property bool hovered: false
    property bool pressed: false
    anchors.fill: parent
    anchors.margins: Style.space(4)
    radius: Style.cornerRadius
    // Pressed beats the keyboard cursor beats hover, as the shell's Button
    // orders them; the fill is the theme's pressed token.
    color: pressed ? Style.pressedFillFor(root.text, Commons.Color.accent)
      : focused ? Commons.Color.menu.selectedBackground
      : (hovered && !appMenu.visible ? Style.hoverFill : "transparent")
    borderSpec: ringed ? root.focusRing : Border.none()
  }

  // A menu entry's own glyph on a square faintly tinted in its group colour.
  component GlyphTile: Item {
    id: tile
    property var entry: null
    property color tint: Commons.Color.accent
    property bool neutral: false
    property int cursorIndex: -1
    readonly property bool focused: !root.searching && root.keyFocus("body", cursorIndex)
    readonly property bool off: root.isOff(entry)
    // Label lines; a tile with more grows by them.
    property int lines: root.labelLines
    width: root.cellWidth
    height: root.cellHeight + (lines - root.labelLines) * Math.ceil(labelMetrics.height)
    opacity: off ? 0.45 : 1

    CellHighlight {
      focused: tile.focused
      hovered: tileHover.hovered
      pressed: tileMouse.pressed && !tile.off
    }

    PressScale {
      id: tileSqueeze
      pressed: tileMouse.pressed && !tile.off
    }
    Rectangle {
      id: square
      scale: tileSqueeze.value
      anchors.horizontalCenter: parent.horizontalCenter
      y: Style.space(10)
      width: root.iconSize
      height: root.iconSize
      radius: Style.cornerRadius
      // The theme's selected-fill strength, in the group's palette colour;
      // the session's tiles take the plain selected fill.
      color: tile.neutral ? Style.selectedFill : Util.alpha(tile.tint, Style.selectedFillAlpha)
      Text {
        anchors.centerIn: parent
        text: tile.entry ? tile.entry.icon : ""
        color: tile.neutral ? root.text : tile.tint
        font.family: root.glyphFont(tile.entry)
        font.pixelSize: Math.round(root.iconSize * 0.46)
      }
    }
    Text {
      anchors.top: square.bottom
      anchors.topMargin: Style.spacing.md
      anchors.horizontalCenter: parent.horizontalCenter
      width: parent.width - Style.space(8)
      textFormat: Text.PlainText
      text: tile.entry ? tile.entry.label : ""
      color: tile.focused ? Commons.Color.menu.selectedText : root.text
      font.family: Style.font.menuFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.Wrap
      maximumLineCount: tile.lines
      elide: Text.ElideRight
    }
    // A pointer that hovers; a finger leaves no highlight behind.
    HoverHandler { id: tileHover; acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad }
    MouseArea {
      id: tileMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: tile.off ? Qt.ArrowCursor : Qt.PointingHandCursor
      onClicked: root.runEntry(tile.entry)
    }
  }

  // One search or recents row: an app, a menu entry with its path, a file.
  // Marked as the Omarchy menu marks its selected row: the theme's menu
  // selection background, text and border.
  component ResultRow: BorderSurface {
    id: resultRow
    property var row: null
    property int cursorIndex: -1
    // The top result is marked even before a key moves: Enter runs it.
    property bool showsTop: false
    readonly property bool keyed: root.searching && root.keyFocus("body", cursorIndex)
    readonly property bool focused: keyed || (showsTop && root.topMark(cursorIndex))
    onKeyedChanged: if (keyed) {
      root.keyedItem = resultRow
      root.keyedApp = row && row.kind === "app" ? row.app : null
      root.keyedRow = row
    }
    readonly property var menuEntry: row && row.kind === "menu" ? row.entry : null
    readonly property var app: row && row.kind === "app" ? row.app
      : (row && row.kind === "file" && row.file.app ? DesktopEntries.byId(String(row.file.app).replace(/\.desktop$/, "")) : null)
    readonly property bool off: !!menuEntry && root.isOff(menuEntry)

    height: root.rowHeight
    radius: Style.cornerRadius
    color: rowMouse.pressed ? Style.pressedFillFor(root.text, Commons.Color.accent)
      : focused ? Commons.Color.menu.selectedBackground
      : (rowHover.hovered ? Style.hoverFill : "transparent")
    borderSpec: keyed ? root.focusRing : (focused ? root.selectedBorderSpec : Border.none())
    opacity: off ? 0.45 : 1

    Rectangle {
      id: rowIcon
      x: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(36)
      height: Style.space(36)
      radius: Style.cornerRadius
      color: resultRow.menuEntry ? Style.selectedAccentFill : "transparent"
      Text {
        visible: !!resultRow.menuEntry
        anchors.centerIn: parent
        text: resultRow.menuEntry ? resultRow.menuEntry.icon : ""
        color: Commons.Color.accent
        font.family: root.glyphFont(resultRow.menuEntry)
        font.pixelSize: Style.font.heading
      }
      Image {
        visible: !resultRow.menuEntry
        anchors.fill: parent
        sourceSize: Qt.size(width * 2, height * 2)
        source: resultRow.menuEntry || !root.appLibrary ? ""
          : (resultRow.app ? root.appLibrary.iconSource(resultRow.app.icon) : Quickshell.iconPath("text-x-generic", true))
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
      }
    }

    Column {
      anchors.left: rowIcon.right
      anchors.leftMargin: Style.space(14)
      anchors.right: parent.right
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(3)

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: {
          var r = resultRow.row
          if (!r) return ""
          if (r.kind === "menu") return root.menu ? root.menu.labelFor(r.entry) : r.entry.label
          if (r.kind === "app") return root.appLibrary ? root.appLibrary.entryName(r.app) : ""
          return r.file.name
        }
        color: resultRow.focused ? Commons.Color.menu.selectedText : root.text
        font.family: Style.font.menuFamily
        font.pixelSize: Style.font.subtitle
        font.bold: resultRow.focused
        elide: Text.ElideRight
      }
      Text {
        width: parent.width
        textFormat: Text.PlainText
        visible: text !== ""
        text: {
          var r = resultRow.row
          if (!r) return ""
          if (r.kind === "menu") return root.menu ? root.menu.pathFor(r.entry.id) : ""
          if (r.kind === "file") return r.file.folder
          return r.time ? root.ageText(r.time) : ""
        }
        color: root.faint
        font.family: Style.font.menuFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideMiddle
      }
    }

    // A pointer that hovers; a finger leaves no highlight behind.
    HoverHandler { id: rowHover; acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad }
    MouseArea {
      id: rowMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: resultRow.off ? Qt.ArrowCursor : Qt.PointingHandCursor
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      onPressAndHold: function(event) {
        if (root.scrolling()) return
        if (resultRow.row && resultRow.row.kind === "app") root.openAppMenu(resultRow.row.app, resultRow.mapToItem(panel.contentItem, event.x, event.y), resultRow, resultRow.row)
      }
      onClicked: function(event) {
        if (event.button === Qt.RightButton) {
          if (resultRow.row && resultRow.row.kind === "app") root.openAppMenu(resultRow.row.app, resultRow.mapToItem(panel.contentItem, event.x, event.y), resultRow, resultRow.row)
          return
        }
        root.runRow(resultRow.row)
      }
    }
  }

  component MenuRow: Rectangle {
    id: menuRow
    property string text: ""
    property bool checked: false
    property bool keyed: false
    signal triggered()

    width: parent ? parent.width : 0
    height: visible ? Math.max(Style.spacing.popupRowHeight, root.touchMin) : 0
    radius: Style.cornerRadius
    color: menuRowMouse.pressed ? Style.pressedFillFor(Commons.Color.popups.text, Commons.Color.accent)
      : (keyed ? Commons.Color.menu.selectedBackground : (menuRowHover.hovered ? Style.hoverFill : "transparent"))
    border.width: keyed ? Math.max(1, Style.focusBorderWidth) : 0
    border.color: Commons.Color.accent

    Text {
      anchors.verticalCenter: parent.verticalCenter
      anchors.left: parent.left
      anchors.leftMargin: Style.spacing.controlPaddingX
      anchors.right: check.left
      textFormat: Text.PlainText
      text: menuRow.text
      color: Commons.Color.popups.text
      font.family: Style.font.menuFamily
      font.pixelSize: Style.font.body
      elide: Text.ElideRight
    }
    Text {
      id: check
      anchors.verticalCenter: parent.verticalCenter
      anchors.right: parent.right
      anchors.rightMargin: Style.spacing.controlPaddingX
      text: menuRow.checked ? "✓" : ""
      color: Commons.Color.accent
      font.family: Style.font.menuFamily
      font.pixelSize: Style.font.body
    }
    // A pointer that hovers; a finger leaves no highlight behind.
    HoverHandler { id: menuRowHover; acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad }
    MouseArea {
      id: menuRowMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: menuRow.triggered()
    }
  }

  // --------------------------------------------------------------- pages

  // Apps on an iPad: one scrolling grid, Add apps… last.
  Component {
    id: padAppsPage

    GridView {
      id: padGrid
      property var pageData: null
      cellWidth: root.cellWidth
      cellHeight: root.cellHeight
      boundsBehavior: Flickable.StopAtBounds
      flickableDirection: Flickable.VerticalFlick
      clip: true
      model: root.appTileCount
      Component.onCompleted: root.appGridView = padGrid
      Component.onDestruction: if (root.appGridView === padGrid) root.appGridView = null

      delegate: Item {
        required property int index
        width: root.cellWidth
        height: root.cellHeight

        AppTile {
          anchors.fill: parent
          visible: index < root.apps.length
          app: index < root.apps.length ? root.apps[index] : null
          cursorIndex: index
        }
        AddAppsTile {
          anchors.fill: parent
          visible: index >= root.apps.length
          cursorIndex: index
        }
      }
    }
  }

  // One page of a phone's apps: as many rows of four as fit.
  Component {
    id: phoneAppsPage

    Item {
      id: phonePage
      property var pageData: null
      readonly property int first: pageData ? pageData.page * root.perPage : 0

      Grid {
        columns: root.columns
        Repeater {
          model: Math.max(0, Math.min(root.perPage, root.apps.length - phonePage.first))
          AppTile {
            required property int index
            width: root.cellWidth
            height: root.cellHeight
            app: root.apps[phonePage.first + index] || null
            cursorIndex: phonePage.first + index
          }
        }
      }
    }
  }

  // Actions, or on a phone System: tinted glyph tiles in groups.
  Component {
    id: groupsPage

    Flickable {
      id: groupsFlick
      property var pageData: null
      readonly property bool session: !!pageData && pageData.tab === "system"
      contentHeight: groupsColumn.height
      boundsBehavior: Flickable.StopAtBounds
      flickableDirection: Flickable.VerticalFlick
      clip: true

      Column {
        id: groupsColumn
        width: groupsFlick.width
        spacing: Style.space(4)

        Repeater {
          model: groupsFlick.session
            ? [{ key: "session", label: Commons.I18n.t("launcher.session"), color: "", entries: root.sessionEntries }]
            : root.actionGroups

          Column {
            id: groupColumn
            required property var modelData
            required property int index
            width: groupsColumn.width
            readonly property int start: {
              if (groupsFlick.session) return 0
              var n = 0
              for (var g = 0; g < index; g++) n += root.actionGroups[g].entries.length
              return n
            }

            Heading {
              visible: !groupsFlick.session && root.actionGroups.length > 1
              text: groupColumn.modelData.label
            }

            Grid {
              columns: root.columns
              Repeater {
                model: groupColumn.modelData.entries
                GlyphTile {
                  required property var modelData
                  required property int index
                  entry: modelData
                  tint: groupColumn.modelData.key === "session"
                    ? (modelData.id === "system.shutdown" ? Commons.Color.urgent : root.text)
                    : root.groupColor(groupColumn.modelData.color)
                  neutral: groupColumn.modelData.key === "session" && modelData.id !== "system.shutdown"
                  cursorIndex: groupColumn.start + index
                }
              }
            }
          }
        }
      }
    }
  }
}
