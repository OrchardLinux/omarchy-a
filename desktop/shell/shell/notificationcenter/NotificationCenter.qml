import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../plugins/panels/weather" as Weather

// The notification center (SHELL-SPEC, step 3): "Today" (a large clock, the
// date, the weather) and the notifications, over upstream's notification
// history: what is on screen and what timed out, was swiped away or was
// replaced, grouped by app. An iPad in landscape has the two side by side,
// portrait and a phone have them stacked. A finger pulls it down from the
// bar's left two thirds (the control center has the right third), the clock
// opens it as a popup, Home, Escape or a tap on the empty screen put it away.
// It moves as the control center does: the finger holds the bottom of what
// it shows, a spring carries it on, and software rendering skips the fades.
Item {
  id: root

  property var shell: null
  property bool opened: false
  property bool mapped: false
  property real reveal: 0
  // Opened once: the weather is fetched from then on, not from shell start.
  property bool everOpened: false

  readonly property bool gpu: Quickshell.env("QT_QUICK_BACKEND") !== "software"
  readonly property real screenWidth: panel.width > 0 ? panel.width : 1024
  readonly property real screenHeight: panel.height > 0 ? panel.height : 768
  readonly property bool phone: Math.min(screenWidth, screenHeight) < 600
  readonly property bool wide: !phone && screenWidth > screenHeight
  readonly property int barInset: Style.bar.sizeHorizontal
  readonly property color text: Commons.Color.popups.text
  readonly property color dim: Qt.darker(text, 1.45)
  readonly property color cardFill: {
    var c = Commons.Color.notifications.background
    return Qt.rgba(c.r, c.g, c.b, 1)
  }
  readonly property color outline: Style.normalBorderFor(text, Commons.Color.accent)
  readonly property real hairline: Style.normalBorderWidth > 0 ? 1 / Math.max(1, panel.devicePixelRatio) : 0

  // Columns: the design's margins and widths, a phone's narrower.
  readonly property real margin: phone ? Style.space(16) : wide ? Style.space(64) : Style.space(40)
  readonly property real todayWidth: wide ? Style.space(300) : screenWidth - margin * 2
  readonly property real listWidth: wide ? Math.min(Style.space(548), screenWidth - margin * 2 - todayWidth - Style.space(48))
                                         : screenWidth - margin * 2

  readonly property var service: shell ? shell.firstPartyServiceFor("omarchy.notifications") : null

  // ------------------------------------------------------------ content

  // Groups of entries, newest first; a group of several shows its newest
  // with "n more" until it is opened.
  // Kept up to date while closed too: built only as it opened, its first
  // frames went into making the cards and the opening stuttered.
  readonly property var groups: {
    var revision = service ? service.centerRevision : 0
    return service ? service.centerGroups() : []
  }
  property var openGroups: ({})
  // What was on the list while it was open: something newer arriving then
  // comes in with a transition; what was there on opening does not.
  property var seen: ({})
  function markAllSeen() {
    var next = {}
    for (var g = 0; g < root.groups.length; g++)
      for (var r = 0; r < root.groups[g].rows.length; r++) next[root.groups[g].rows[r].key] = true
    root.seen = next
  }
  function toggleGroup(key) {
    var next = {}
    for (var k in openGroups) next[k] = openGroups[k]
    if (next[key]) delete next[key]; else next[key] = true
    openGroups = next
  }

  // The time, to the minute, for the clock and the cards' ages.
  property double now: Date.now()
  Timer {
    interval: 1000 * (60 - new Date().getSeconds())
    running: root.mapped
    repeat: true
    triggeredOnStart: true
    onTriggered: { root.now = Date.now(); interval = 1000 * (60 - new Date().getSeconds()) }
  }
  function ago(ts) {
    var s = Math.max(0, (root.now - ts * 1000) / 1000)
    if (s < 60) return I18n.t("agents.durationNow")
    if (s < 3600) return Math.round(s / 60) + " min"
    if (s < 86400) return Math.round(s / 3600) + " h"
    return Qt.locale(I18n.formatLocale).toString(new Date(ts * 1000), "ddd")
  }

  // The weather panel, hosted for its data only (never shown).
  QtObject {
    id: weatherHost
    readonly property color foreground: root.text
    readonly property color barForeground: root.text
    readonly property color urgent: Commons.Color.urgent
    readonly property string fontFamily: Style.font.family
    readonly property var shell: root.shell
    readonly property string position: "top"
    readonly property bool vertical: false
    readonly property int barSize: Style.bar.sizeHorizontal
    readonly property var activePopout: null
    readonly property bool foregroundAnimationEnabled: false
    readonly property int sizeHorizontal: Style.bar.sizeHorizontal
    readonly property int iconFont: Style.font.icon
    readonly property int iconSize: Style.font.icon
    readonly property int iconSlot: Style.space(28)
    readonly property bool iconCanvas: false
    readonly property var clickTargets: []
    function barSizeFor() { return Style.bar.sizeHorizontal }
    function showTooltip() {}
    function hideTooltip() {}
    function requestPopout() { return false }
    function releasePopout() {}
    function notePopoutCard() {}
    function popoutCardFor() { return null }
    function targetBelongsToWindow() { return false }
    function run(command) { Quickshell.execDetached(["sh", "-c", command]) }
    function switchPanelFrom(panel, direction) { return false }
    function showPage(panel) {}
    function leavePage(panel) {}
  }
  Item {
    visible: false
    Loader {
      id: weatherLoader
      active: root.everOpened
      sourceComponent: Weather.Panel { host: weatherHost; bar: weatherHost; moduleName: "omarchy.weather" }
    }
  }
  readonly property var weather: weatherLoader.item
  readonly property bool hasWeather: !!weather && weather.reportTempNum !== ""
  readonly property string weatherHighLow: {
    if (!weather || !weather.forecastDays || weather.forecastDays.length === 0) return ""
    var day = weather.forecastDays[0]
    var high = weather.bareTempForDay(day, "max"), low = weather.bareTempForDay(day, "min")
    return high !== "" && low !== "" ? "H " + high + " · L " + low : ""
  }

  // ------------------------------------------------------------ opening

  function closePopout() {
    var bar = root.shell ? root.shell.bar : null
    var popout = bar ? bar.activePopout : null
    if (popout && typeof popout.close === "function") popout.close()
  }
  // Nothing else of the shell's lies under it: a bar popup, the control
  // center and the launcher go first, and they put it away in turn.
  function clearOthers() {
    root.closePopout()
    if (root.shell && root.shell.controlCenter && root.shell.controlCenter.opened) root.shell.controlCenter.close()
    if (root.shell && root.shell.launcher && root.shell.launcher.opened) root.shell.launcher.close()
  }
  Connections {
    target: root.shell ? root.shell.bar : null
    function onActivePopoutChanged() { if (root.opened && root.shell.bar.activePopout) root.close() }
  }

  function show() {
    root.clearOthers()
    root.everOpened = true
    // Stacks open closed again, and the list starts at the top.
    root.openGroups = ({})
    root.markAllSeen()
    scroller.contentY = 0
    root.focusIndex = -1
    root.opened = true
    root.mapped = true
    if (panel.contentRevealed) root.animateIn()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }
  function open() { root.popupStyle = false; root.show() }
  function close() {
    root.touchSpent = false
    if (!root.opened) return
    root.closingFromOpen = true
    root.opened = false
    if (root.popupStyle) { spring.running = false; popupOut.restart() }
    else root.settle(0, 0)
  }
  function toggle() { root.opened ? root.close() : root.open() }
  // From the clock, with a mouse: a popup's fade, no slide, the bar not dimmed.
  property bool popupStyle: false
  function togglePopup() {
    if (root.opened) { root.close(); return }
    root.popupStyle = !root.phone
    root.show()
  }
  function animateIn() {
    if (root.popupStyle) { spring.running = false; popupOut.stop(); popupIn.restart() }
    else root.settle(1, 0)
  }
  NumberAnimation {
    id: popupIn
    target: root; property: "reveal"; to: 1
    duration: root.gpu ? Style.duration(180) : 0
    easing.type: Easing.Bezier
    easing.bezierCurve: Style.easeOut
  }
  NumberAnimation {
    id: popupOut
    target: root; property: "reveal"; to: 0
    duration: root.gpu ? Style.duration(140) : 0
    easing.type: Easing.InOutCubic
    onFinished: if (!root.opened) root.mapped = false
  }

  // While open, a note for the Home button (omarchy-home-button closes it),
  // written by one writer until it matches.
  readonly property string openNote: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/omarchy-notification-center-open"
  property bool noteWritten: true
  function writeOpenNote() {
    if (noteWriter.running || root.noteWritten === root.opened) return
    noteWriter.writing = root.opened
    noteWriter.command = root.opened ? ["touch", root.openNote] : ["rm", "-f", root.openNote]
    noteWriter.running = true
  }
  Process {
    id: noteWriter
    property bool writing: false
    onExited: { root.noteWritten = writing; root.writeOpenNote() }
  }
  Component.onCompleted: writeOpenNote()
  onOpenedChanged: {
    writeOpenNote()
    if (!opened && typing) endReply()
  }

  ShellIpc {
    target: "omarchy.notificationcenter"
    function toggle(): void { root.toggle() }
    function open(): void { if (!root.opened) root.open() }
    function close(): void { root.close() }
  }

  // ------------------------------------------------------------ the pull

  // A finger pulls it down from the bar, or pushes it up to put it away: the
  // bottom of what it shows follows the finger; let go, a spring carries it
  // on or back by how far and fast it moved.
  property bool pulling: false
  property bool touchSpent: false
  property real pullFrom: 0
  readonly property real pullSpan: Math.max(1, root.barInset + Math.min(content.height, root.screenHeight - root.barInset))

  function beginPull() {
    spring.running = false
    popupIn.stop()
    popupOut.stop()
    root.popupStyle = false
    if (!root.opened) {
      root.clearOthers()
      root.everOpened = true
      root.openGroups = ({})
      root.markAllSeen()
      scroller.contentY = 0
      root.reveal = 0
      root.mapped = true
    }
    root.pullFrom = root.reveal
    root.pulling = true
  }
  function pullTo(distance) {
    if (!root.pulling) return
    var r = root.pullFrom + distance / root.pullSpan
    if (r > 1) r = 1 + (1 - 1 / (1 + (r - 1) * 2)) * 0.08
    root.reveal = Math.max(0, r)
  }
  function endPull(velocity) {
    if (!root.pulling) return
    root.pulling = false
    var flick = Style.space(400)
    var keep = velocity > flick || (velocity > -flick && root.reveal > 0.4)
    root.closingFromOpen = !keep && root.pullFrom > 0.5
    root.opened = keep
    root.settle(keep ? 1 : 0, velocity / root.pullSpan)
    if (keep) Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  property real springTarget: 0
  property real springVelocity: 0
  function settle(target, velocity) {
    root.springTarget = target
    root.springVelocity = velocity
    spring.running = true
  }
  property bool closingFromOpen: false
  readonly property bool leaving: root.pulling ? root.pullFrom > 0.5 : (!root.opened && root.closingFromOpen)
  FrameAnimation {
    id: spring
    onTriggered: {
      var elapsed = Math.min(frameTime, 0.25)
      var stiffness = root.springTarget > 0 ? 260 : 195
      var damping = 2 * Math.sqrt(stiffness) * (root.springTarget > 0 ? 0.86 : 1.0)
      var steps = Math.max(1, Math.ceil(elapsed / (1 / 240)))
      var dt = elapsed / steps
      var reveal = root.reveal, velocity = root.springVelocity
      for (var i = 0; i < steps; i++) {
        velocity += (-stiffness * (reveal - root.springTarget) - damping * velocity) * dt
        reveal += velocity * dt
      }
      root.springVelocity = velocity
      root.reveal = reveal
      if (Math.abs(root.reveal - root.springTarget) < 0.002 && Math.abs(root.springVelocity) < 0.02) {
        root.reveal = root.springTarget
        root.springVelocity = 0
        running = false
        if (!root.opened) root.mapped = false
      }
    }
  }
  readonly property bool moving: spring.running || root.pulling || popupIn.running || popupOut.running

  // ------------------------------------------------------------ keyboard

  // Up and Down walk Focus, Clear all and the cards; Enter opens or presses,
  // Delete clears a card, Escape closes.
  property int focusIndex: -1
  readonly property int focusCount: 2 + root.groups.length
  function moveFocus(step) {
    if (root.focusCount === 0) return
    root.focusIndex = root.focusIndex < 0 ? (step > 0 ? 0 : root.focusCount - 1)
      : Math.max(0, Math.min(root.focusCount - 1, root.focusIndex + step))
  }
  function activateFocused() {
    if (root.focusIndex === 0) root.toggleFocus()
    else if (root.focusIndex === 1) root.clearAll()
    else if (root.focusIndex >= 2) root.openGroup(root.groups[root.focusIndex - 2])
  }
  function forgetFocused() {
    if (root.focusIndex >= 2) root.forgetGroup(root.groups[root.focusIndex - 2], false)
  }

  // ------------------------------------------------------------ actions

  readonly property bool focusOn: !!service && service.doNotDisturb === true
  function toggleFocus() { if (service) service.setDoNotDisturb(!root.focusOn) }
  function clearAll() { if (service) service.clearCenter() }
  function openEntry(entry) {
    if (!service || !entry) return
    service.openEntry(entry)
    root.close()
  }
  function openGroup(group) { if (group && group.rows.length) root.openEntry(group.rows[0]) }
  // A sender's button, or its inline reply: the center goes first, since the
  // press changes the list and so remakes the card it came from.
  function pressAction(entry, id) {
    var key = entry.key, live = entry.live
    root.close()
    if (service && live) service.invokeAction(key, id)
  }
  function sendReply(entry, text) {
    var key = entry.key
    root.endReply()
    root.close()
    if (service) service.sendReply(key, text)
  }
  // A reply field being typed in: the on-screen keyboard (opened for a
  // finger) lies over the center then, and goes with the reply.
  property bool typing: false
  property bool replyKeyboard: false
  function beginReply(byTouch) {
    root.typing = true
    if (byTouch && !root.replyKeyboard) {
      root.replyKeyboard = true
      Quickshell.execDetached([(Quickshell.env("OMARCHY_PATH") || "/usr/share/omarchy") + "/bin/omarchy-keyboard", "show"])
    }
  }
  function endReply() {
    root.typing = false
    if (root.replyKeyboard) {
      root.replyKeyboard = false
      Quickshell.execDetached([(Quickshell.env("OMARCHY_PATH") || "/usr/share/omarchy") + "/bin/omarchy-keyboard", "hide"])
    }
    keyCatcher.forceActiveFocus()
  }

  // A collapsed stack goes whole; an open one, the card swiped.
  function forgetGroup(group, single, entry) {
    if (!service || !group) return
    if (single && entry) { service.forgetEntry(entry.key); return }
    for (var i = 0; i < group.rows.length; i++) service.forgetEntry(group.rows[i].key)
  }

  // ------------------------------------------------------------ window

  OverlayWindow {
    id: panel
    shown: root.mapped
    // Above everything, the on-screen keyboard included, except while a
    // reply is typed: then under it, so the keyboard is there to type with.
    shownLayer: root.typing ? WlrLayer.Top : WlrLayer.Overlay
    WlrLayershell.namespace: "omarchy-notification-center"
    // The bar stays the bar's: a pull from it or a click on its items reaches it.
    mask: Region { item: belowBar }
    Item {
      id: belowBar
      y: root.barInset
      width: parent.width
      height: Math.max(0, parent.height - root.barInset)
    }

    onContentRevealedChanged: if (contentRevealed && root.opened && !root.pulling) {
      root.reveal = 0
      root.animateIn()
      keyCatcher.forceActiveFocus()
    }

    // The screen under it dims (a phone's is the sheet itself), and a tap on
    // what is not a card puts it away.
    Rectangle {
      id: scrim
      y: root.barInset
      width: parent.width
      height: parent.height - y
      // The lock screen's scrim: even, the theme's lock scrim, and on a dark
      // theme taken toward black so it does not grey the wallpaper to mud.
      // The wallpaper stays a hint behind the cards.
      readonly property color lockScrim: Commons.Color.lock.scrim
      readonly property bool darkTheme: (0.2126 * lockScrim.r + 0.7152 * lockScrim.g + 0.0722 * lockScrim.b) < 0.5
      color: darkTheme ? Qt.rgba(lockScrim.r * 0.42, lockScrim.g * 0.42, lockScrim.b * 0.42, lockScrim.a) : lockScrim
      opacity: !root.gpu ? (root.reveal > 0 ? 1 : 0)
        : root.leaving ? sheet.opacity
        : 1 - Math.pow(1 - Math.max(0, Math.min(1, root.reveal)), 2.5)
      MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: root.close()
      }
      // Pushed up on the empty screen, it follows and goes away; only while
      // there is nothing to scroll, or it would take a scroll's swipe and
      // close instead (the handle at the bottom, Home and Escape always do).
      DragHandler {
        target: null
        xAxis.enabled: false
        acceptedDevices: PointerDevice.TouchScreen
        enabled: (root.opened || root.pulling) && !scroller.interactive
        onActiveChanged: active ? root.beginPull() : root.endPull(centroid.velocity.y)
        onTranslationChanged: if (active) root.pullTo(translation.y)
      }
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true
      Keys.onPressed: function(event) {
        switch (event.key) {
        case Qt.Key_Escape: root.close(); break
        case Qt.Key_Down: case Qt.Key_Tab: root.moveFocus(1); break
        case Qt.Key_Up: case Qt.Key_Backtab: root.moveFocus(-1); break
        case Qt.Key_Return: case Qt.Key_Enter: case Qt.Key_Space: root.activateFocused(); break
        case Qt.Key_Delete: case Qt.Key_Backspace: root.forgetFocused(); break
        default: return
        }
        event.accepted = true
      }
    }
    PointHandler { onActiveChanged: if (active) root.focusIndex = -1 }

    // What it shows, sliding down from under the bar: its bottom is where the
    // finger is. As a popup it fades and grows from 97 % instead.
    Item {
      id: sheet
      y: root.barInset
      width: parent.width
      height: parent.height - root.barInset
      clip: true
      layer.enabled: root.moving && root.gpu
      layer.smooth: true
      readonly property real follow: Math.min(content.height, height)
      // Pulled, it slides (the bottom of what it shows at the finger) and
      // lands with the spring's small swing past its place; as a popup it
      // grows from 97 %.
      readonly property real grow: !root.gpu ? 1 : (root.popupStyle ? 0.97 + 0.03 * root.reveal : 1)
      transform: [
        Scale { origin.x: sheet.width / 2; origin.y: 0; xScale: sheet.grow; yScale: sheet.grow },
        Translate { y: root.popupStyle ? 0 : (root.reveal - 1) * sheet.follow }
      ]
      opacity: !root.gpu ? (root.reveal > 0 ? 1 : 0) : root.popupStyle ? root.reveal : root.leaving
        ? Math.max(0, Math.min(1, root.reveal * 1.2 - 0.2))
        : 1 - Math.pow(1 - Math.max(0, Math.min(1, root.reveal / 0.3)), 2)

      Flickable {
        id: scroller
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.height
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Item {
          id: content
          width: scroller.width
          height: Math.max(root.wide ? todayColumn.y + todayColumn.height : 0, listColumn.y + listColumn.height) + Style.space(root.phone ? 24 : 40)

          // ---- Today
          // Landscape: a column of its own at the left, the clock large.
          // Portrait and a phone: one row over the notifications, the clock
          // and the date at the left and the weather at the right, so the
          // notifications start near the top.
          Column {
            id: todayColumn
            visible: root.wide
            x: root.margin
            y: Style.space(40)
            width: root.todayWidth
            height: root.wide ? implicitHeight : todayRow.height
            spacing: Style.space(8)

            Text {
              textFormat: Text.PlainText
              text: Qt.locale(I18n.formatLocale).toString(new Date(root.now), "HH:mm")
              color: root.text
              font.family: Style.font.family
              font.pixelSize: Style.space(72)
              font.bold: true
            }
            Text {
              textFormat: Text.PlainText
              text: Qt.locale(I18n.formatLocale).toString(new Date(root.now), "dddd, d MMMM")
              color: root.text
              font.family: Style.font.family
              font.pixelSize: Style.font.subtitle
            }
            Item { width: 1; height: Style.space(16); visible: root.hasWeather }
            WeatherCard { width: parent.width; visible: root.hasWeather }
          }

          Item {
            id: todayRow
            visible: !root.wide
            x: root.margin
            y: Style.space(root.phone ? 16 : 28)
            width: root.screenWidth - root.margin * 2
            height: Math.max(clockBlock.implicitHeight, compactWeather.visible ? compactWeather.height : 0)
            Column {
              id: clockBlock
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)
              Text {
                textFormat: Text.PlainText
                text: Qt.locale(I18n.formatLocale).toString(new Date(root.now), "HH:mm")
                color: root.text
                font.family: Style.font.family
                font.pixelSize: Style.space(root.phone ? 34 : 40)
                font.bold: true
              }
              Text {
                textFormat: Text.PlainText
                text: Qt.locale(I18n.formatLocale).toString(new Date(root.now), "dddd, d MMMM")
                color: root.dim
                font.family: Style.font.family
                font.pixelSize: Style.font.body
              }
            }
            WeatherCard {
              id: compactWeather
              visible: root.hasWeather
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              width: Math.min(implicitWidth, parent.width - clockBlock.implicitWidth - Style.space(16))
            }
          }

          // ---- Notifications
          Column {
            id: listColumn
            x: root.wide ? root.screenWidth - root.margin - root.listWidth : root.margin
            y: root.wide ? Style.space(40) : todayRow.y + todayRow.height + Style.space(root.phone ? 20 : 28)
            width: root.listWidth
            spacing: Style.space(12)

            // The header: Focus (Do Not Disturb) and Clear all.
            Item {
              width: parent.width
              height: Math.max(heading.implicitHeight, headerButtons.height)
              Text {
                id: heading
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: I18n.t("notificationCenter.title")
                color: root.text
                font.family: Style.font.family
                font.pixelSize: Style.font.title
                font.bold: true
              }
              Row {
                id: headerButtons
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(8)
                HeaderButton {
                  glyph: "󰽥"
                  label: root.focusOn ? I18n.t("notificationCenter.focusOn") : I18n.t("notificationCenter.focusOff")
                  lit: root.focusOn
                  focused: root.focusIndex === 0
                  onActivated: root.toggleFocus()
                }
                HeaderButton {
                  label: I18n.t("notificationCenter.clearAll")
                  enabled: root.groups.length > 0
                  focused: root.focusIndex === 1
                  onActivated: root.clearAll()
                }
              }
            }

            Text {
              visible: root.groups.length === 0
              width: parent.width
              topPadding: Style.space(24)
              horizontalAlignment: Text.AlignHCenter
              textFormat: Text.PlainText
              text: I18n.t("notificationCenter.empty")
              color: root.dim
              font.family: Style.font.family
              font.pixelSize: Style.font.subtitle
            }

            Repeater {
              model: root.groups
              Item {
                id: groupColumn
                required property var modelData
                required property int index
                readonly property bool open: !!root.openGroups[modelData.key]
                readonly property int more: modelData.rows.length - 1
                // 0 closed, 1 open: the stack's cards slide out from under its
                // head and fade in, what follows moving down with them.
                property real openness: open ? 1 : 0
                Behavior on openness {
                  enabled: root.gpu
                  NumberAnimation { duration: Style.duration(300); easing.type: Easing.InOutCubic }
                }
                width: listColumn.width
                // Arriving while open: a new app's group grows in from
                // nothing at the top and fades in, what follows moving down;
                // a group that was there takes its new message as a fade of
                // its head.
                property real appear: 1
                property real headAppear: 1
                NumberAnimation on appear {
                  id: appearRun
                  running: false
                  to: 1
                  duration: root.gpu ? Style.duration(320) : 0
                  easing.type: Easing.Bezier
                  easing.bezierCurve: Style.easeOut
                }
                NumberAnimation on headAppear {
                  id: headAppearRun
                  running: false
                  to: 1
                  duration: root.gpu ? Style.duration(260) : 0
                  easing.type: Easing.InOutCubic
                }
                Component.onCompleted: {
                  var rows = modelData.rows, unseen = 0
                  for (var i = 0; i < rows.length; i++) if (!root.seen[rows[i].key]) unseen++
                  if (root.mapped && unseen > 0) {
                    if (unseen === rows.length) { appear = 0; appearRun.start() }
                    else { headAppear = 0; headAppearRun.start() }
                  }
                  for (var j = 0; j < rows.length; j++) root.seen[rows[j].key] = true
                }
                clip: appear < 1
                opacity: appear
                height: (head.height + (rest.active && rest.item ? rest.item.height : 0)) * appear

                CenterCard {
                  id: head
                  z: 1
                  y: -(1 - groupColumn.appear) * Style.space(16)
                  opacity: groupColumn.headAppear
                  width: groupColumn.width
                  entry: groupColumn.modelData.rows[0]
                  more: groupColumn.open ? -1 : groupColumn.more
                  // The shapes fade and fold away with the opening, not at once.
                  stacked: groupColumn.more
                  shade: 1 - groupColumn.openness
                  focused: root.focusIndex === groupColumn.index + 2
                  onOpened: root.openEntry(entry)
                  onSwiped: root.forgetGroup(groupColumn.modelData, groupColumn.open, entry)
                  onMoreToggled: root.toggleGroup(groupColumn.modelData.key)
                  onActionPressed: function(id) { root.pressAction(entry, id) }
                  onReplySent: function(text) { root.sendReply(entry, text) }
                }
                // The rest of the stack, built only while it shows.
                Loader {
                  id: rest
                  active: groupColumn.more > 0 && (groupColumn.open || groupColumn.openness > 0)
                  y: head.height
                  width: groupColumn.width
                  sourceComponent: Column {
                    width: groupColumn.width
                    topPadding: Style.space(8) * groupColumn.openness
                    spacing: Style.space(8) * groupColumn.openness
                    opacity: groupColumn.openness
                    Repeater {
                      model: groupColumn.modelData.rows.slice(1)
                      Item {
                        required property var modelData
                        width: groupColumn.width
                        height: restCard.height * groupColumn.openness
                        CenterCard {
                          id: restCard
                          width: parent.width
                          // From under the head: each card starts higher up.
                          y: -(1 - groupColumn.openness) * height
                          entry: parent.modelData
                          onOpened: root.openEntry(entry)
                          onSwiped: root.forgetGroup(groupColumn.modelData, true, entry)
                          onActionPressed: function(id) { root.pressAction(entry, id) }
                          onReplySent: function(text) { root.sendReply(entry, text) }
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
    }

    // Pushed up from the screen's bottom edge (labwc leaves that swipe to
    // it), it follows the finger and goes: nothing drawn, only where a swipe
    // from the edge lands, which stays put so the drag measures against
    // something still.
    Item {
      anchors.bottom: parent.bottom
      width: parent.width
      height: Style.space(28)
      visible: root.mapped && !root.popupStyle
      DragHandler {
        target: null
        xAxis.enabled: false
        acceptedDevices: PointerDevice.TouchScreen
        enabled: root.opened || root.pulling
        onActiveChanged: active ? root.beginPull() : root.endPull(centroid.velocity.y)
        onTranslationChanged: if (active) root.pullTo(translation.y)
      }
    }
  }

  // ------------------------------------------------------------ parts

  // The weather, as the weather panel reads it.
  component WeatherCard: Rectangle {
    implicitWidth: weatherRow.implicitWidth + Style.space(28)
    height: weatherRow.implicitHeight + Style.space(20)
    color: root.cardFill
    border.width: root.hairline
    border.color: root.outline
    clip: true
    Row {
      id: weatherRow
      x: Style.space(14)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(12)
      Text {
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: root.weather ? root.weather.label : ""
        color: Commons.Color.accent
        font.family: Style.font.family
        font.pixelSize: Style.font.displayLarge
      }
      Column {
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)
        Text {
          textFormat: Text.PlainText
          text: root.weather ? root.weather.reportTempNum + root.weather.tempUnit : ""
          color: root.text
          font.family: Style.font.family
          font.pixelSize: Style.font.title
          font.bold: true
        }
        Text {
          textFormat: Text.PlainText
          text: [root.weatherHighLow, root.weather ? root.weather.reportLocation : ""]
            .filter(function(part) { return part !== "" }).join(" · ")
          color: root.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  // A small outlined button of the header; lit in the accent while on.
  component HeaderButton: Rectangle {
    id: button
    property string glyph: ""
    property string label: ""
    property bool lit: false
    property bool focused: false
    signal activated()
    width: buttonRow.implicitWidth + Style.space(20)
    height: Style.space(30)
    color: lit ? Util.alpha(Commons.Color.accent, 0.18) : "transparent"
    border.width: root.hairline
    border.color: focused ? Commons.Color.accent : root.outline
    opacity: enabled ? 1 : 0.45
    scale: buttonArea.pressed && buttonArea.containsMouse ? 0.96 : 1
    Row {
      id: buttonRow
      anchors.centerIn: parent
      spacing: Style.space(6)
      Text {
        visible: button.glyph !== ""
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: button.glyph
        color: button.lit ? Commons.Color.accent : root.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: button.label
        color: button.lit ? Commons.Color.accent : root.text
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }
    MouseArea {
      id: buttonArea
      anchors.fill: parent
      enabled: button.enabled
      preventStealing: true
      onClicked: button.activated()
    }
  }

  // One notification, laid out as a banner: the app's icon at the left, a
  // bold title with the time at its end, the body, the sender's own buttons
  // under the text; the app's name only when there is no icon. "n more"
  // opens its stack. A tap opens it, a finger sliding it sideways clears it
  // (kinetic, as the banners).
  component CenterCard: Item {
    id: card
    property var entry: ({})
    property int more: 0          // >0 the head of a stack (closed), -1 the head of an open one
    // How many cards it heads (its shapes stay while they fade out).
    property int stacked: more > 0 ? more : 0
    // How much of a closed stack's shapes behind it shows (1 closed, 0 open).
    property real shade: 1
    property bool focused: false
    signal opened()
    signal swiped()
    signal moreToggled()
    signal actionPressed(string id)
    signal replySent(string text)
    readonly property int shapes: Math.min(2, stacked)
    height: box.height + Style.space(6) * shapes * shade

    readonly property string iconUrl: root.service ? root.service.iconFor(entry) : ""
    readonly property string glyph: String(entry.glyph || "")
    readonly property bool hasIcon: iconUrl !== "" || glyph !== ""
    readonly property string appName: root.service ? root.service.nameFor(entry) : ""
    readonly property real iconSize: root.phone ? Style.space(36) : Style.space(40)

    // The cards behind a closed stack, as shapes; they fade as it opens.
    Repeater {
      model: card.shapes
      // Each lies behind the card above and reaches up under it, so that
      // card's opaque face covers its top edge: two half-transparent
      // outlines on one row of pixels would add up to a brighter line.
      Rectangle {
        required property int index
        readonly property real under: Style.space(6)
        z: -1 - index
        x: Style.space(8) * (index + 1)
        y: box.height + Style.space(6) * index * card.shade - under
        width: card.width - Style.space(16) * (index + 1)
        height: Style.space(6) + under
        color: root.cardFill
        border.width: root.hairline
        border.color: root.outline
        opacity: (0.8 - index * 0.25) * card.shade
      }
    }

    property real swipeX: 0
    property real flingVelocity: 0
    property string fling: ""
    Rectangle {
      id: box
      x: card.swipeX
      width: card.width
      height: content.implicitHeight + Style.space(24)
      color: root.cardFill
      border.width: root.focused ? Math.max(1, root.hairline) : root.hairline
      border.color: card.focused ? Commons.Color.accent : root.outline
      opacity: Math.max(0, 1 - Math.abs(card.swipeX) / (card.width * 0.5))
      layer.enabled: root.gpu && (card.fling !== "" || swipe.active)

      MouseArea {
        anchors.fill: parent
        onClicked: card.opened()
      }

      Column {
        id: content
        x: Style.space(12)
        y: Style.space(12)
        width: parent.width - Style.space(26)
        spacing: Style.space(10)

        Row {
          width: parent.width
          spacing: Style.space(12)

          // Without an icon, a quiet square with a bell keeps every card's
          // text in line.
          Item {
            id: icon
            width: card.iconSize
            height: width
            Rectangle {
              anchors.fill: parent
              visible: !card.hasIcon
              color: Util.alpha(root.text, 0.08)
              Text {
                anchors.centerIn: parent
                textFormat: Text.PlainText
                text: "󰂚"
                color: root.dim
                font.family: Style.font.family
                font.pixelSize: Style.font.title
              }
            }
            Image {
              anchors.fill: parent
              visible: card.iconUrl !== ""
              source: card.iconUrl
              sourceSize.width: width * 2
              sourceSize.height: height * 2
              fillMode: Image.PreserveAspectFit
              asynchronous: true
            }
            Text {
              anchors.centerIn: parent
              visible: card.iconUrl === "" && card.glyph !== ""
              textFormat: Text.PlainText
              text: card.glyph
              color: root.text
              font.family: Style.font.family
              font.pixelSize: Style.font.displayLarge
            }
          }

          Column {
            width: parent.width - (icon.visible ? icon.width + parent.spacing : 0)
            spacing: Style.space(3)

            Item {
              width: parent.width
              height: title.implicitHeight
              Text {
                id: title
                width: parent.width - meta.width - Style.space(8)
                textFormat: Text.PlainText
                text: String(card.entry.summary || "")
                color: root.text
                font.family: Style.font.family
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
              }
              Row {
                id: meta
                anchors.right: parent.right
                anchors.verticalCenter: title.verticalCenter
                spacing: Style.space(8)
                Text {
                  visible: !card.hasIcon && card.appName !== ""
                  textFormat: Text.PlainText
                  text: card.appName
                  color: root.dim
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                }
                Text {
                  visible: card.more !== 0
                  textFormat: Text.PlainText
                  text: card.more > 0 ? I18n.t("notificationCenter.more").arg(card.more) : I18n.t("notificationCenter.less")
                  color: Commons.Color.accent
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  MouseArea {
                    anchors.fill: parent
                    anchors.margins: -Style.space(10)
                    preventStealing: true
                    onClicked: card.moreToggled()
                  }
                }
                Text {
                  textFormat: Text.PlainText
                  text: root.ago(card.entry.ts || 0)
                  color: root.dim
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                }
              }
            }
            Text {
              visible: text !== ""
              width: parent.width
              textFormat: Text.PlainText
              text: String(card.entry.body || "")
              color: root.dim
              font.family: Style.font.family
              font.pixelSize: Style.font.subtitle
              wrapMode: Text.Wrap
              maximumLineCount: 3
              elide: Text.ElideRight
            }
          }
        }

        // The sender's own buttons under the text: the first in the accent.
        Row {
          readonly property var actions: card.entry.actions || []
          visible: actions.length > 0
          x: icon.visible ? icon.width + Style.space(12) : 0
          width: parent.width - x
          spacing: Style.space(8)
          Repeater {
            model: parent.actions
            Rectangle {
              required property var modelData
              required property int index
              width: (parent.width - Style.space(8) * (card.entry.actions.length - 1)) / card.entry.actions.length
              height: Style.space(32)
              color: index === 0 ? Commons.Color.accent : "transparent"
              border.width: index === 0 ? 0 : root.hairline
              border.color: root.outline
              scale: actionArea.pressed && actionArea.containsMouse ? 0.96 : 1
              Text {
                anchors.centerIn: parent
                width: parent.width - Style.space(12)
                horizontalAlignment: Text.AlignHCenter
                textFormat: Text.PlainText
                text: String(parent.modelData.text || "")
                color: parent.index === 0 ? Commons.Color.background : root.text
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                font.bold: parent.index === 0
                elide: Text.ElideRight
              }
              MouseArea {
                id: actionArea
                anchors.fill: parent
                preventStealing: true
                onClicked: card.actionPressed(String(parent.modelData.id))
              }
            }
          }
        }

        // The sender's inline reply, as on a banner.
        Row {
          visible: String(card.entry.reply || "") !== ""
          x: icon.visible ? icon.width + Style.space(12) : 0
          width: parent.width - x
          spacing: Style.space(8)
          Rectangle {
            width: parent.width - sendBox.width - parent.spacing
            height: Style.space(34)
            color: Util.alpha(Commons.Color.background, 0.7)
            border.width: replyInput.activeFocus && root.typing ? Math.max(1, root.hairline) : root.hairline
            border.color: replyInput.activeFocus && root.typing ? Commons.Color.accent : root.outline
            TextInput {
              id: replyInput
              anchors.fill: parent
              anchors.leftMargin: Style.space(10)
              anchors.rightMargin: Style.space(10)
              verticalAlignment: TextInput.AlignVCenter
              color: root.text
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              clip: true
              activeFocusOnPress: false
              onAccepted: if (text.trim() !== "") card.replySent(text)
              Keys.onEscapePressed: { text = ""; root.endReply() }
              Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: parent.text === ""
                textFormat: Text.PlainText
                text: String(card.entry.reply || "")
                color: root.dim
                font: parent.font
              }
            }
            Item {
              anchors.fill: parent
              visible: !(replyInput.activeFocus && root.typing)
              TapHandler {
                onTapped: function(point) {
                  root.beginReply(point.device.type === PointerDevice.TouchScreen)
                  replyInput.forceActiveFocus()
                }
              }
            }
          }
          Rectangle {
            id: sendBox
            width: Style.space(34)
            height: Style.space(34)
            color: Commons.Color.accent
            scale: sendArea.pressed && sendArea.containsMouse ? 0.96 : 1
            Text {
              anchors.centerIn: parent
              textFormat: Text.PlainText
              text: "\uf1d8"
              color: Commons.Color.background
              font.family: Style.font.family
              font.pixelSize: Style.font.title
            }
            MouseArea {
              id: sendArea
              anchors.fill: parent
              preventStealing: true
              onClicked: if (replyInput.text.trim() !== "") card.replySent(replyInput.text)
            }
          }
        }
      }
    }

    // A finger slides it sideways; let go, kinetic as a banner's: thrown it
    // clears, kept it springs back.
    DragHandler {
      id: swipe
      target: null
      yAxis.enabled: false
      acceptedDevices: PointerDevice.TouchScreen
      grabPermissions: PointerHandler.CanTakeOverFromItems | PointerHandler.CanTakeOverFromHandlersOfDifferentType
      onActiveChanged: {
        if (active) { card.fling = ""; return }
        var v = centroid.velocity.x
        var away = Math.abs(card.swipeX) > card.width * 0.35 || Math.abs(v) > Style.space(500)
        if (!root.gpu) { if (away) card.swiped(); else card.swipeX = 0; return }
        if (away) {
          var direction = card.swipeX + v * 0.05 >= 0 ? 1 : -1
          card.flingVelocity = direction * Math.max(Math.abs(v), Style.space(900))
          card.fling = "away"
        } else {
          card.flingVelocity = v
          card.fling = "back"
        }
      }
      onTranslationChanged: if (active) card.swipeX = translation.x
    }
    FrameAnimation {
      running: card.fling !== ""
      onTriggered: {
        var elapsed = Math.min(frameTime, 0.05)
        var steps = Math.max(1, Math.ceil(elapsed / (1 / 240)))
        var dt = elapsed / steps, x = card.swipeX, v = card.flingVelocity
        for (var i = 0; i < steps; i++) {
          if (card.fling === "away") {
            v *= Math.pow(0.35, dt)
            if (Math.abs(v) < Style.space(900)) v = (v < 0 ? -1 : 1) * Style.space(900)
          } else {
            v += (-260 * x - 2 * Math.sqrt(260) * 0.85 * v) * dt
          }
          x += v * dt
        }
        card.flingVelocity = v
        card.swipeX = x
        if (card.fling === "away" && Math.abs(x) >= card.width * 0.5) { card.fling = ""; card.swiped(); card.swipeX = 0 }
        else if (card.fling === "back" && Math.abs(x) < 0.5 && Math.abs(v) < Style.space(10)) { card.fling = ""; card.swipeX = 0 }
      }
    }
  }
}
