import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "SettingsLayout.js" as Layout
import "SettingsModel.js" as Model

// The window: a sidebar of sections beside the page (wide), or the section
// list and then a page over it (narrow, a phone). Rows come from the layout
// and the menu (SettingsModel.js); a row does what its menu entry does.
FloatingWindow {
  id: win

  property var host: null
  property var menu: null

  title: Commons.I18n.t("settings.title")
  color: Commons.Color.background
  implicitWidth: 980
  implicitHeight: 700
  minimumSize: Qt.size(320, 420)
  visible: true

  onClosed: if (host) host.close()

  // ------------------------------------------------------------- the data

  readonly property color text: Commons.Color.foreground
  readonly property color dim: Util.alpha(Commons.Color.foreground, 0.6)
  readonly property color faint: Util.alpha(Commons.Color.foreground, 0.4)
  readonly property color fill: Util.alpha(Commons.Color.foreground, 0.04)
  readonly property color line: Util.alpha(Commons.Color.foreground, 0.12)
  readonly property color accent: Commons.Color.accent

  readonly property bool wide: content.width >= Style.space(640)
  readonly property bool twoColumns: content.width >= Style.space(940)
  readonly property int rowHeight: Style.space(42)
  readonly property int pad: Style.space(20)
  readonly property int sidebarWidth: content.width >= Style.space(940) ? Style.space(260) : Style.space(216)

  // What the menu knows now; every row reads it.
  property var values: ({})
  property var missing: ({})
  property var hyprland: ({})
  // A switch flipped a moment ago shows its new state until the menu has
  // checked again.
  property var pending: ({})
  readonly property var ctx: ({
    items: menu ? menu.items : ({}),
    itemOrder: menu ? menu.itemOrder : [],
    whenResults: menu ? menu.whenResults : ({}),
    checkedResults: menu ? menu.checkedResults : ({}),
    disabledResults: menu ? menu.disabledResults : ({}),
    values: values,
    missing: missing,
    hyprland: hyprland
  })
  readonly property var providers: menu ? menu.providers : ({})
  function t(key) { return Commons.I18n.t(key) }

  readonly property var sections: Layout.SECTIONS
  readonly property var sectionBlocks: {
    var out = []
    for (var i = 0; i < sections.length; i++) {
      if (i === 0 || sections[i].startsGroup) out.push([])
      out[out.length - 1].push(sections[i])
    }
    return out
  }

  function sectionById(id) {
    for (var i = 0; i < sections.length; i++) if (sections[i].id === id) return sections[i]
    return null
  }
  function sectionIcon(section) {
    if (section.icon) return section.icon
    var e = ctx.items[section.iconEntry]
    return e ? e.icon : ""
  }

  // ------------------------------------------------------------ navigation

  // The section shown ("" on a phone: the list of sections), and the pages
  // opened inside it: { kind: "menu" | "choice" | "native", id, page }.
  property string section: ""
  property var stack: []
  property string query: ""
  readonly property bool searching: query.trim() !== ""

  // A page comes in over the one before from the right and leaves to the
  // right again, as on an iPad: the old page is held as a picture while the
  // new one is built, so both move together. On a phone the section list is
  // a page too; on a wide window the sidebar stays and a section shows in
  // place. Without a GPU (software rendering) pages change at once.
  readonly property bool gpu: Quickshell.env("QT_QUICK_BACKEND") !== "software"
  property int navDirection: 0
  property real navT: 1
  property var navChange: null
  property bool navPhone: false
  property var navPicture: null
  function navigate(direction, change) {
    if (!win.gpu || direction === 0 || content.width <= 0 || navAnim.running || navWait.running) {
      if (navAnim.running) navAnim.complete()
      change()
      return
    }
    win.navPhone = !win.wide
    // A phone's whole window moves; a wide window's page only.
    var picture = win.navPhone ? shot : pageShot
    picture.sourceItem = win.navPhone ? content : pageMover
    if (win.navPhone) {
      shot.x = 0
      shot.width = content.width
      shot.height = content.height
    }
    // Only a picture in the scene is taken: shown (too faint to see) until
    // it has the old page.
    win.navT = 1
    picture.visible = true
    picture.scheduleUpdate()
    win.navPicture = picture
    win.navDirection = direction
    win.navChange = change
    navWait.start()
  }
  // A frame for the picture to be taken before the page changes under it.
  Timer {
    id: navWait
    interval: 34
    onTriggered: {
      win.navChange()
      win.navChange = null
      win.navT = 0
      navAnim.restart()
    }
  }
  NumberAnimation {
    id: navAnim
    target: win; property: "navT"; from: 0; to: 1
    duration: Style.duration(340)
    easing.type: Easing.OutCubic
    onFinished: {
      if (win.navPicture) { win.navPicture.visible = false; win.navPicture.sourceItem = null }
      win.navPicture = null
      win.navDirection = 0
    }
  }
  readonly property real navWidth: navPhone ? content.width : pageArea.width
  // Where the new page and the picture of the old one stand now.
  readonly property real slideNew: navDirection > 0 ? (1 - navT) * navWidth
    : navDirection < 0 ? -(1 - navT) * navWidth * 0.3 : 0
  readonly property real slideOld: navDirection > 0 ? -navT * navWidth * 0.3
    : navDirection < 0 ? navT * navWidth : 0

  function goSection(id) {
    // From a phone's list into a section: a page in.
    if (!win.wide && win.section === "" && id !== "" && !win.searching) {
      win.navigate(1, function() { win.showSection(id) })
      return
    }
    win.showSection(id)
  }
  function showSection(id) {
    if (id !== "" && id !== sections[0].id) win.chosen = true
    win.section = id
    win.stack = []
    win.query = ""
    searchField.text = ""
    win.cursor = -1
    scroller.contentY = 0
  }
  function push(page) {
    win.navigate(1, function() { win.pushNow(page) })
  }
  function pushNow(page) {
    win.stack = win.stack.concat([page])
    win.cursor = -1
    scroller.contentY = 0
    if (page.kind === "choice") {
      var e = ctx.items[page.id]
      if (e && e.provider && menu) {
        menu.invalidateVolatileProvider(page.id)
        menu.loadProviderForMenu(page.id)
      }
    }
  }
  function back() {
    if (win.searching) { win.query = ""; searchField.text = ""; return true }
    if (win.stack.length > 0) {
      win.navigate(-1, function() { win.stack = win.stack.slice(0, -1); win.cursor = -1 })
      return true
    }
    if (!win.wide && win.section !== "") {
      win.navigate(-1, function() { win.section = ""; win.cursor = -1 })
      return true
    }
    return false
  }
  function openPath(path) {
    var r = Model.route(path, sections, ctx)
    win.chosen = r.section !== ""
    win.showSection(r.section || (win.wide ? sections[0].id : ""))
    if (r.page) win.pushNow(r.page)
  }
  // Opened without a page: a wide window shows its first section beside the
  // list, a phone the list itself. The window learns its width only once it
  // is placed, so the choice follows it until a section is picked.
  property bool chosen: false
  onWideChanged: {
    if (win.chosen || win.stack.length > 0 || win.searching) return
    win.section = win.wide ? sections[0].id : ""
  }

  readonly property var top: stack.length > 0 ? stack[stack.length - 1] : null

  readonly property string pageTitle: {
    if (win.searching) return win.t("settings.searchResults")
    if (top) {
      if (top.kind === "native") {
        var nativeEntry = { theme: "appearance.theme", background: "appearance.background", icons: "appearance.icons" }[top.page]
        return nativeEntry && ctx.items[nativeEntry] ? ctx.items[nativeEntry].label : top.page
      }
      var e = ctx.items[top.id]
      return e ? (e.title || e.label) : ""
    }
    var s = sectionById(win.section)
    return s ? win.t(s.label) : win.t("settings.title")
  }
  // "Appearance ›" above a page opened inside a section.
  readonly property string backLabel: {
    if (!top) return ""
    if (stack.length > 1) {
      var prev = stack[stack.length - 2]
      var e = prev.kind === "native" ? null : ctx.items[prev.id]
      return e ? e.label : ""
    }
    var s = sectionById(win.section)
    return s ? win.t(s.label) : ""
  }

  // The rows the page shows, in groups.
  readonly property var groups: {
    var c = win.ctx
    if (win.searching) {
      var found = Model.search(win.query, sections, c, providers, win.t)
      return found.length ? [{ label: "", rows: found.slice(0, 60) }] : []
    }
    if (top) {
      if (top.kind === "menu") return [{ label: "", rows: Model.resolveRows(Model.menuSpecs(c, top.id), c, providers, win.t) }]
      if (top.kind === "choice") return [{ label: "", rows: Model.choiceRows(c, c.items[top.id]) }]
      return []
    }
    return Model.sectionGroups(sectionById(win.section), c, providers, win.t)
  }
  readonly property var nativePage: {
    if (win.searching) return ""
    if (top && top.kind === "native") return top.page
    var s = sectionById(win.section)
    return !top && s && s.page ? s.page : ""
  }
  readonly property var flatRows: {
    var out = []
    for (var g = 0; g < groups.length; g++) for (var r = 0; r < groups[g].rows.length; r++) out.push(groups[g].rows[r])
    return out
  }

  // ----------------------------------------------------------- doing things

  function activate(row) {
    if (!row || row.available === false || row.off) return
    if (row.section !== undefined && row.section !== win.section && win.searching) {
      // A search result opens where it lives, then does what it does.
      var target = row
      win.goSection(row.section || win.section || sections[0].id)
      win.activate(target)
      return
    }
    if (row.kind === "switch") {
      var next = Object.assign({}, win.pending)
      next[row.key] = !row.on
      win.pending = next
      run(row.entry.action)
      return
    }
    if (row.kind === "choice") { win.push({ kind: "choice", id: row.entry.id }); return }
    if (row.kind === "page") { win.push({ kind: "menu", id: row.entry.id }); return }
    if (row.kind === "native") {
      if (sectionById(win.section) && sectionById(win.section).page === row.page && !top) return
      win.push({ kind: "native", page: row.page })
      return
    }
    if (row.kind === "option" || row.kind === "action") run(row.entry.action)
  }

  function run(action) {
    if (!action || !menu) return
    menu.runAction(action)
    refreshSoon.restart()
  }

  function switchOn(row) {
    return win.pending[row.key] !== undefined ? win.pending[row.key] === true : row.on === true
  }

  // What changed shows as soon as the menu has checked again: right after
  // a change, and once more for commands that take a moment.
  Timer { id: refreshSoon; interval: 500; onTriggered: { win.refresh(); refreshLater.restart() } }
  Timer { id: refreshLater; interval: 2000; onTriggered: win.refresh() }
  function refresh() {
    if (menu) menu.evaluateGuards()
    stateProc.collected = ""
    stateProc.command = ["bash", "-lc", Model.stateScript(sections, ctx, providers)]
    stateProc.running = true
  }
  Connections {
    target: win.menu
    function onWhenResultsChanged() { win.pending = ({}) }
  }
  Process {
    id: stateProc
    property string collected: ""
    stdout: SplitParser { onRead: function(data) { stateProc.collected += data + "\n" } }
    onExited: {
      var s = Model.parseState(stateProc.collected)
      win.values = s.values
      win.missing = s.missing
      win.hyprland = s.hyprland
    }
  }

  Component.onCompleted: {
    if (host) openPath(host.path)
    refresh()
    content.forceActiveFocus()
  }
  Connections {
    target: win.host
    function onPathRevisionChanged() { if (win.host.path) win.openPath(win.host.path) }
  }

  // ------------------------------------------------------------- keyboard

  // A cursor over the page's rows, shown once a key moves it.
  property int cursor: -1
  function moveCursor(step) {
    var n = win.flatRows.length
    if (n === 0) return
    var i = win.cursor
    for (var tries = 0; tries < n; tries++) {
      i = i < 0 ? (step > 0 ? 0 : n - 1) : (i + step + n) % n
      if (win.flatRows[i].available !== false && !win.flatRows[i].off) break
    }
    win.cursor = i
  }
  function moveSection(step) {
    var i = 0
    for (var k = 0; k < sections.length; k++) if (sections[k].id === win.section) i = k
    win.goSection(sections[(i + step + sections.length) % sections.length].id)
  }

  // ---------------------------------------------------------------- layout

  // The old page during a transition: under the new one going forward, over
  // it going back; a shade deepens on it as it moves under.
  ShaderEffectSource {
    id: shot
    visible: false
    live: false
    hideSource: false
    // It fades as it goes; while it is being taken (navT still 1) it is too
    // faint to see.
    opacity: Math.max(0.01, 1 - win.navT)
    z: win.navDirection < 0 ? 2 : -1
    transform: Translate { x: win.slideOld }
    Rectangle {
      anchors.fill: parent
      color: "black"
      opacity: win.navDirection > 0 ? 0.18 * win.navT : 0
    }
  }

  Item {
    id: content
    anchors.fill: parent
    focus: true
    transform: Translate { x: win.navPhone && win.navDirection !== 0 ? win.slideNew : 0 }
    // Opaque, so the page going forward covers the picture under it.
    Rectangle { anchors.fill: parent; color: win.color; visible: win.navPhone && win.navDirection !== 0 }

    Keys.onPressed: function(event) {
      var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
      if (event.key === Qt.Key_Down) { win.moveCursor(1); event.accepted = true }
      else if (event.key === Qt.Key_Up) { win.moveCursor(-1); event.accepted = true }
      else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
        if (win.cursor >= 0 && win.cursor < win.flatRows.length) win.activate(win.flatRows[win.cursor])
        event.accepted = true
      }
      else if (event.key === Qt.Key_Escape || event.key === Qt.Key_Backspace || (event.key === Qt.Key_Left && (event.modifiers & Qt.AltModifier))) {
        event.accepted = win.back()
      }
      else if (event.key === Qt.Key_PageDown || (ctrl && event.key === Qt.Key_Tab)) { win.moveSection(1); event.accepted = true }
      else if (event.key === Qt.Key_PageUp || (ctrl && event.key === Qt.Key_Backtab)) { win.moveSection(-1); event.accepted = true }
      else if ((ctrl && event.key === Qt.Key_F) || event.key === Qt.Key_Slash) { searchField.forceActiveFocus(); event.accepted = true }
      else if (event.text && event.text.length === 1 && event.text > " " && !ctrl) {
        searchField.forceActiveFocus()
        searchField.text += event.text
        event.accepted = true
      }
    }

    // ------------------------------------------------------------ sidebar

    Item {
      id: sidebar
      visible: win.wide || win.section === ""
      width: win.wide ? win.sidebarWidth : parent.width
      height: parent.height

      Flickable {
        anchors.fill: parent
        contentHeight: sideColumn.height + win.pad * 2
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: sideColumn
          x: win.pad
          y: win.pad
          width: parent.width - win.pad * (win.wide ? 1.5 : 2)
          spacing: Style.space(14)

          Text {
            text: win.t("settings.title")
            color: win.text
            font.family: Style.font.family
            font.pixelSize: Style.font.display
            font.bold: true
          }

          // Search: every setting, and every menu entry beside them.
          Rectangle {
            width: parent.width
            height: Style.space(38)
            color: win.fill
            border.width: 1
            border.color: searchField.activeFocus ? Util.alpha(win.accent, 0.7) : win.line
            Text {
              id: searchGlyph
              x: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              text: ""
              color: win.faint
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.body
            }
            TextInput {
              id: searchField
              x: searchGlyph.x + searchGlyph.width + Style.space(10)
              width: parent.width - x - Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              color: win.text
              font.family: Style.font.family
              font.pixelSize: Style.font.subtitle
              selectionColor: Util.alpha(win.accent, 0.4)
              clip: true
              onTextChanged: { win.query = text; win.cursor = -1 }
              Keys.onPressed: function(event) {
                if (event.key === Qt.Key_Escape) { text = ""; content.forceActiveFocus(); event.accepted = true }
                else if (event.key === Qt.Key_Down || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                  content.forceActiveFocus()
                  if (event.key === Qt.Key_Down) win.moveCursor(1)
                  else if (win.flatRows.length > 0) win.activate(win.flatRows[0])
                  event.accepted = true
                }
              }
              Text {
                visible: searchField.text === ""
                text: win.t("settings.search")
                color: win.faint
                font: searchField.font
              }
            }
          }

          // A phone's search results, under the field.
          Text {
            visible: !win.wide && win.searching && win.groups.length === 0
            text: win.t("settings.noResults")
            color: win.faint
            font.family: Style.font.family
            font.pixelSize: Style.font.subtitle
          }
          Repeater {
            model: !win.wide && win.searching ? win.groups : []
            Group {
              required property var modelData
              width: sideColumn.width
              group: modelData
            }
          }

          // The sections; on a phone, the root list with what each holds, in
          // one box with a line between rows.
          // The sections fall into kinds (startsGroup), a gap between.
          Column {
            width: parent.width
            visible: !(win.searching && !win.wide)
            spacing: win.wide ? Style.space(12) : Style.space(16)
            Repeater {
              model: win.sectionBlocks
          Rectangle {
            id: block
            required property var modelData
            width: parent.width
            height: sectionList.height + (win.wide ? 0 : 2)
            color: win.wide ? "transparent" : win.fill
            border.width: win.wide ? 0 : 1
            border.color: win.line
          Column {
            id: sectionList
            x: win.wide ? 0 : 1
            y: win.wide ? 0 : 1
            width: parent.width - (win.wide ? 0 : 2)
            spacing: win.wide ? Style.space(2) : 0
            Repeater {
              model: block.modelData
              Rectangle {
                id: sectionRow
                required property var modelData
                required property int index
                readonly property bool current: win.wide && win.section === modelData.id && !win.searching
                width: parent.width
                height: win.wide ? Style.space(40) : Style.space(54)
                color: current ? Util.alpha(win.accent, 0.14) : "transparent"
                Rectangle {
                  visible: !win.wide && sectionRow.index > 0
                  width: parent.width; height: 1
                  color: Util.alpha(win.text, 0.07)
                }
                Rectangle {
                  visible: sectionRow.current
                  width: Style.space(2); height: parent.height
                  color: win.accent
                }
                Text {
                  id: sectionGlyph
                  x: Style.space(12)
                  width: Style.space(22)
                  anchors.verticalCenter: parent.verticalCenter
                  text: win.sectionIcon(sectionRow.modelData)
                  color: sectionRow.current || !win.wide ? win.accent : win.dim
                  font.family: Style.font.menuFamily
                  font.pixelSize: Style.font.title
                  horizontalAlignment: Text.AlignHCenter
                }
                Column {
                  x: sectionGlyph.x + sectionGlyph.width + Style.space(12)
                  width: parent.width - x - Style.space(30)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(2)
                  Text {
                    width: parent.width
                    text: win.t(sectionRow.modelData.label)
                    color: win.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.subtitle
                    font.bold: sectionRow.current
                    elide: Text.ElideRight
                  }
                  // What it holds: its groups, as the section itself names them.
                  Text {
                    visible: !win.wide && text !== ""
                    width: parent.width
                    text: {
                      var names = []
                      var gs = sectionRow.modelData.groups
                      for (var i = 0; i < gs.length && names.length < 3; i++) if (gs[i].label) names.push(win.t(gs[i].label))
                      return names.join(", ")
                    }
                    color: win.faint
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    elide: Text.ElideRight
                  }
                }
                Text {
                  visible: !win.wide
                  anchors.right: parent.right
                  anchors.rightMargin: Style.space(14)
                  anchors.verticalCenter: parent.verticalCenter
                  text: "›"
                  color: win.faint
                  font.family: Style.font.family
                  font.pixelSize: Style.font.heading
                }
                TapHandler { onTapped: { win.chosen = true; win.goSection(sectionRow.modelData.id) } }
              }
            }
          }
          }
            }
          }
        }
      }
    }

    // --------------------------------------------------------------- page

    Item {
      id: pageArea
      // On a phone a search shows under its field, in the list.
      visible: win.wide || win.section !== ""
      x: win.wide ? sidebar.width : 0
      width: parent.width - x
      height: parent.height
      // On a wide window a page moves within its own area, never over the
      // sidebar.
      clip: true

      // The old page during a transition here: under the new one going
      // forward, over it going back.
      ShaderEffectSource {
        id: pageShot
        width: pageArea.width
        height: pageArea.height
        visible: false
        live: false
        hideSource: false
        opacity: Math.max(0.01, 1 - win.navT)
        z: win.navDirection < 0 ? 2 : 0
        transform: Translate { x: win.slideOld }
        Rectangle {
          anchors.fill: parent
          color: "black"
          opacity: win.navDirection > 0 ? 0.18 * win.navT : 0
        }
      }

      Item {
        id: pageMover
        anchors.fill: parent
        z: 1
        transform: Translate { x: !win.navPhone && win.navDirection !== 0 ? win.slideNew : 0 }
        // Opaque, so the page going forward covers the picture under it.
        Rectangle { anchors.fill: parent; color: win.color; visible: !win.navPhone && win.navDirection !== 0 }

        Flickable {
          id: scroller
          anchors.fill: parent
          contentHeight: pageColumn.height + win.pad * 2
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentHeight > height

          Column {
            id: pageColumn
            x: win.pad
            y: win.pad
            width: parent.width - win.pad * 2
            spacing: Style.space(14)

            // Back and the title. On a phone the back reads "‹ Settings" at
            // the top of a section.
            Item {
              width: parent.width
              height: Math.max(titleText.height, backRow.visible ? backRow.height : 0)
              Row {
                id: backRow
                visible: win.stack.length > 0 || (!win.wide && (win.section !== "" || win.searching))
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)
                // A drawn chevron, so it sits on the label's middle whatever
                // the font does with its glyphs.
                Item {
                  width: Style.space(10)
                  height: backLabelText.height
                  anchors.verticalCenter: parent.verticalCenter
                  Repeater {
                    model: [-1, 1]
                    Rectangle {
                      required property var modelData
                      width: Style.space(9)
                      height: Math.max(2, Style.space(2))
                      radius: height / 2
                      color: win.accent
                      antialiasing: true
                      x: Style.space(1)
                      y: (parent.height - height) / 2
                      rotation: modelData * 45
                      transformOrigin: Item.Left
                    }
                  }
                }
                Text {
                  id: backLabelText
                  text: win.stack.length > 0 ? win.backLabel : win.t("settings.title")
                  color: win.accent
                  font.family: Style.font.family
                  font.pixelSize: Style.font.subtitle
                  anchors.verticalCenter: parent.verticalCenter
                }
                TapHandler { onTapped: win.back() }
              }
              // On a phone the title stands in the middle, as a phone's
              // settings show it; on a wide window after the back link.
              Text {
                id: titleText
                readonly property bool centered: !win.wide && backRow.visible
                // Worked out from the back link and the text alone, so where it
                // stands and how wide it is never wait on each other.
                readonly property real leftEdge: backRow.visible ? backRow.width + Style.space(centered ? 12 : 16) : 0
                readonly property real titleWidth: centered
                  ? Math.min(implicitWidth, parent.width - 2 * leftEdge)
                  : parent.width - leftEdge - (moreButton.visible ? moreButton.width + Style.space(10) : 0)
                x: centered ? Math.max(leftEdge, (parent.width - titleWidth) / 2) : leftEdge
                width: titleWidth
                horizontalAlignment: centered ? Text.AlignHCenter : Text.AlignLeft
                anchors.verticalCenter: parent.verticalCenter
                text: win.pageTitle
                color: win.text
                font.family: Style.font.family
                font.pixelSize: !backRow.visible ? Style.font.display : Style.font.heading
                font.bold: true
                elide: Text.ElideRight
              }
              // The theme page's "Get more", where the menu offers it.
              Rectangle {
                id: moreButton
                readonly property var entry: win.ctx.items["update.themes"]
                visible: win.nativePage === "theme" && !!entry && Model.shown(win.ctx, entry)
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: moreText.width + Style.space(24)
                height: Style.space(32)
                color: "transparent"
                border.width: 1
                border.color: win.line
                Text {
                  id: moreText
                  anchors.centerIn: parent
                  text: moreButton.entry ? moreButton.entry.label : ""
                  color: win.text
                  font.family: Style.font.family
                  font.pixelSize: Style.font.body
                }
                TapHandler { onTapped: win.run(moreButton.entry.action) }
              }
            }

            Text {
              visible: win.searching && win.groups.length === 0
              text: win.t("settings.noResults")
              color: win.faint
              font.family: Style.font.family
              font.pixelSize: Style.font.subtitle
            }

            Loader {
              width: parent.width
              active: win.nativePage !== ""
              visible: active
              sourceComponent: win.nativePage === "theme" ? themePage
                : win.nativePage === "background" ? backgroundPage
                : win.nativePage === "icons" ? iconsPage
                : win.nativePage === "about" ? aboutPage
              : win.nativePage === "wifi" ? wifiPage
              : win.nativePage === "bluetooth" ? bluetoothPage
              : win.nativePage === "sound" ? soundPage
              : win.nativePage === "display" ? displayPage : null
            }

            // The section's groups: the card first, then two columns where the
            // window is wide enough, one otherwise.
            Repeater {
              model: win.groups.filter(function(g) { return g.card })
              ThemeCard {
                required property var modelData
                width: pageColumn.width
                row: modelData.rows[0]
              }
            }
            Row {
              id: columns
              // A section's own page shows its groups under it (Wi-Fi, About).
            visible: win.nativePage === "" || !win.top
              width: parent.width
              spacing: Style.space(18)
              readonly property var plain: win.groups.filter(function(g) { return !g.card })
              readonly property bool split: win.twoColumns && plain.length > 1 && !win.top && !win.searching
              // Groups go to the shorter column, in order.
              readonly property var halves: {
                var left = [], right = [], lh = 0, rh = 0
                for (var i = 0; i < plain.length; i++) {
                  var h = plain[i].rows.length + (plain[i].label ? 1 : 0) + 1
                  if (!split || lh <= rh) { left.push(plain[i]); lh += h } else { right.push(plain[i]); rh += h }
                }
                return [left, right]
              }
              Repeater {
                model: columns.split ? 2 : 1
                Column {
                  required property int index
                  width: columns.split ? (columns.width - columns.spacing) / 2 : columns.width
                  spacing: Style.space(14)
                  Repeater {
                    model: columns.halves[index]
                    Group {
                      required property var modelData
                      width: parent.width
                      group: modelData
                    }
                  }
                }
              }
            }

          }
        }
      }
    }
  }

  // ----------------------------------------------------------- components

  component Group: Column {
    property var group: null
    spacing: Style.space(6)
    Text {
      visible: !!group && group.label !== ""
      text: group ? group.label.toUpperCase() : ""
      color: win.faint
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      font.letterSpacing: 1.5
      leftPadding: Style.space(2)
    }
    Rectangle {
      width: parent.width
      height: rowsColumn.height + 2
      color: win.fill
      border.width: 1
      border.color: win.line
      Column {
        id: rowsColumn
        x: 1; y: 1
        width: parent.width - 2
        Repeater {
          model: group ? group.rows : []
          SettingRow {
            required property var modelData
            required property int index
            width: rowsColumn.width
            row: modelData
            first: index === 0
          }
        }
      }
    }
  }

  component SettingRow: Item {
    id: rowItem
    property var row: null
    property bool first: false
    readonly property bool usable: !!row && row.available !== false && !row.off
    readonly property bool focused: win.cursor >= 0 && win.flatRows[win.cursor] === row
    readonly property bool isSwitch: !!row && row.kind === "switch"
    readonly property bool opens: !!row && (row.kind === "page" || row.kind === "choice" || row.kind === "native")
    height: win.rowHeight + (row && row.path && win.searching ? Style.space(12) : 0)

    Rectangle {
      visible: !rowItem.first
      width: parent.width; height: 1
      color: Util.alpha(win.text, 0.07)
    }
    Rectangle {
      anchors.fill: parent
      color: rowPress.pressed ? Util.alpha(win.text, 0.08) : (rowItem.focused ? Util.alpha(win.accent, 0.12) : "transparent")
      border.width: rowItem.focused ? 1 : 0
      border.color: Util.alpha(win.accent, 0.6)
    }

    Column {
      x: Style.space(14)
      width: rightSide.x - x - Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(1)
      opacity: rowItem.usable ? 1 : 0.45
      // The name, and after it what it needs that is not here (Hyprland).
      Row {
        width: parent.width
        spacing: Style.space(10)
        Text {
          id: labelText
          width: Math.min(implicitWidth, parent.width - (tagBox.visible ? tagBox.width + parent.spacing : 0))
          anchors.verticalCenter: parent.verticalCenter
          text: rowItem.row ? rowItem.row.label : ""
          color: rowItem.row && rowItem.row.current ? win.accent : win.text
          font.family: Style.font.family
          font.pixelSize: Style.font.subtitle
          elide: Text.ElideRight
        }
        Rectangle {
          id: tagBox
          visible: !!rowItem.row && !!rowItem.row.tag
          anchors.verticalCenter: parent.verticalCenter
          width: tagText.width + Style.space(10)
          height: tagText.height + Style.space(4)
          color: "transparent"
          border.width: 1
          border.color: win.line
          Text {
            id: tagText
            anchors.centerIn: parent
            text: rowItem.row && rowItem.row.tag ? rowItem.row.tag : ""
            color: win.faint
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }
      }
      // Where a search result lives.
      Text {
        visible: !!rowItem.row && !!rowItem.row.path && win.searching
        width: parent.width
        text: rowItem.row && rowItem.row.path ? rowItem.row.path : ""
        color: win.faint
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    Row {
      id: rightSide
      anchors.right: parent.right
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(10)
      opacity: rowItem.usable ? 1 : 0.45
      Text {
        visible: !!rowItem.row && !!rowItem.row.value && !rowItem.isSwitch
        width: Math.min(implicitWidth, rowItem.width * 0.45)
        anchors.verticalCenter: parent.verticalCenter
        text: rowItem.row && rowItem.row.value ? rowItem.row.value : ""
        color: win.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
      }
      Text {
        visible: !!rowItem.row && (rowItem.row.current === true || (!!rowItem.row.off && rowItem.row.kind === "option"))
        anchors.verticalCenter: parent.verticalCenter
        text: "✓"
        color: win.accent
        font.family: Style.font.family
        font.pixelSize: Style.font.title
      }
      ToggleSwitch {
        visible: rowItem.isSwitch
        anchors.verticalCenter: parent.verticalCenter
        checked: rowItem.row ? win.switchOn(rowItem.row) : false
        interactive: false
        cursorRing: false
      }
      Text {
        visible: rowItem.opens
        anchors.verticalCenter: parent.verticalCenter
        text: "›"
        color: win.faint
        font.family: Style.font.family
        font.pixelSize: Style.font.heading
      }
    }

    TapHandler {
      id: rowPress
      enabled: rowItem.usable
      onTapped: win.activate(rowItem.row)
    }
  }

  // The current theme as a card: its colours and name.
  component ThemeCard: Rectangle {
    id: card
    property var row: null
    height: Style.space(84)
    color: win.fill
    border.width: 1
    border.color: win.line
    // The current theme's own colours, from its colors.toml.
    FileView {
      id: themeColors
      path: Quickshell.env("HOME") + "/.local/state/omarchy/current/theme/colors.toml"
      watchChanges: true
      printErrors: false
      onFileChanged: reload()
    }
    Row {
      id: swatches
      x: Style.space(18)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)
      Repeater {
        model: Model.swatchesOf(Model.parseColors(themeColors.loaded ? themeColors.text() : ""))
        Rectangle { required property var modelData; width: Style.space(12); height: width; color: modelData }
      }
    }
    Column {
      x: swatches.x + swatches.width + Style.space(24)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(3)
      Text {
        text: card.row && card.row.value ? card.row.value : (card.row ? card.row.label : "")
        color: win.text
        font.family: Style.font.family
        font.pixelSize: Style.font.title
        font.bold: true
      }
      Text {
        text: card.row ? card.row.label : ""
        color: win.faint
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
    }
    Text {
      anchors.right: parent.right
      anchors.rightMargin: Style.space(16)
      anchors.verticalCenter: parent.verticalCenter
      text: "›"
      color: win.faint
      font.family: Style.font.family
      font.pixelSize: Style.font.heading
    }
    TapHandler { onTapped: if (card.row) win.activate(card.row) }
  }

  // ------------------------------------------------------- native pages

  Component { id: themePage; ThemePage { settings: win } }
  Component { id: backgroundPage; BackgroundPage { settings: win } }
  Component { id: iconsPage; IconsPage { settings: win } }
  Component { id: aboutPage; AboutPage { settings: win } }
  Component { id: wifiPage; WifiPage { settings: win } }
  Component { id: bluetoothPage; BluetoothPage { settings: win } }
  Component { id: soundPage; SoundPage { settings: win } }
  Component { id: displayPage; DisplayPage { settings: win } }
}
