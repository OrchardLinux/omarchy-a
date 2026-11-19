import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Networking
import Quickshell.Wayland
import Quickshell.Services.Pipewire
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../plugins/panels/network" as Network
import "../plugins/panels/bluetooth" as BluetoothStatus
import "../plugins/panels/power" as Power
import "../plugins/panels/bluetooth/Model.js" as BluetoothModel
import "../plugins/status" as StatusParts
import "../plugins/panels/monitor" as Monitor

// The control center (SHELL-SPEC, step 2): the main view. States you flip
// and the two sliders, over the same status objects the bar and the lock
// read. On an iPad a panel below the bar at the right with the screen dimmed;
// on a phone the whole screen. Until its module pages exist, a tile's chevron
// and the battery line open the bar's panels.
Item {
  id: root

  property var shell: null
  property bool opened: false
  property bool mapped: false
  property real reveal: 0

  readonly property bool gpu: Quickshell.env("QT_QUICK_BACKEND") !== "software"
  readonly property real screenWidth: panel.width > 0 ? panel.width : 1024
  readonly property real screenHeight: panel.height > 0 ? panel.height : 768
  readonly property bool phone: Math.min(screenWidth, screenHeight) < 600
  readonly property int barInset: Style.bar.sizeHorizontal
  readonly property int touchMin: Style.space(44)
  readonly property int gap: Style.space(8)
  readonly property int pad: Style.space(12)
  readonly property int cardWidth: phone ? screenWidth : Style.space(356)
  readonly property color text: Commons.Color.popups.text
  readonly property color onFill: Commons.Color.accent
  readonly property color onText: Commons.Color.background

  // ------------------------------------------------------------ state

  Network.Status { id: network }
  BluetoothStatus.Status { id: bluetooth }
  Power.Status { id: battery }
  StatusParts.RotationLock { id: rotation }

  readonly property var idleService: shell ? shell.firstPartyServiceFor("omarchy.idle") : null
  readonly property bool stayAwake: idleService ? idleService.stayAwake === true : false

  readonly property var sink: Pipewire.defaultAudioSink
  readonly property var source: Pipewire.defaultAudioSource
  PwObjectTracker { objects: [root.sink, root.source].filter(function(n) { return !!n }) }
  readonly property real volume: sink && sink.audio ? sink.audio.volume : 0
  readonly property bool micMuted: UntypedInput.active
    ? (!UntypedInput.known || UntypedInput.muted)
    : !(source && source.audio) || source.audio.muted
  readonly property bool micKnown: UntypedInput.active ? UntypedInput.known : !!(source && source.audio)

  property int brightness: -1
  property bool autoBrightness: false

  readonly property string wifiSubtitle: {
    if (!network.wifiEnabled) return Commons.I18n.t("controlCenter.off")
    if (network.hasCaptivePortal) return Commons.I18n.t("controlCenter.signIn")
    if (network.kind === "wifi" && network.ssid !== "") return network.ssid
    if (network.kind === "ethernet") return Commons.I18n.t("controlCenter.wired")
    return Commons.I18n.t("controlCenter.notConnected")
  }
  readonly property string bluetoothSubtitle: {
    if (!bluetooth.enabled) return Commons.I18n.t("controlCenter.off")
    var n = bluetooth.connectedDevices.length
    if (n === 1) return BluetoothModel.deviceLabel(bluetooth.connectedDevices[0])
    if (n > 1) return Commons.I18n.t("controlCenter.connectedCount").arg(Commons.I18n.formatNumber(n))
    return Commons.I18n.t("controlCenter.notConnected")
  }
  readonly property string outputName: sink ? String(sink.nickname || sink.description || "") : ""
  readonly property string batteryLine: {
    if (battery.displayedPercentage === null) return ""
    var line = Commons.I18n.formatNumber(battery.displayedPercentage) + "%"
    var time = String(battery.batteryInfo.time || "")
    return time !== "" && !battery.externalPower ? line + " · " + time : line
  }

  // ---------------------------------------------------------- actions

  function run(argv) { Quickshell.execDetached(argv) }
  function omarchy(name) { return (Quickshell.env("OMARCHY_PATH") || "/usr/share/omarchy") + "/bin/" + name }

  // A module's page: its panel's content, pushed in from the right. A
  // module without a page yet opens the bar's panel for it.
  function openPage(module) {
    var panelForPage = root.modules[module]
    if (panelForPage) { panelForPage.open(); return }
    root.close()
    run(["omarchy-shell", "shell", "toggle", module])
  }

  // ------------------------------------------------------------ pages
  // Each page is a panel of its own (not the bar's), hosted: pageHost stands
  // in for the bar it would read its colours and font from, and opening or
  // closing it shows or leaves the page.

  QtObject {
    id: pageHost
    readonly property color foreground: root.text
    readonly property color barForeground: root.text
    readonly property color urgent: Commons.Color.urgent
    readonly property string fontFamily: Style.font.family
    readonly property var shell: root.shell
    readonly property string position: "top"
    readonly property bool vertical: false
    readonly property int barSize: Style.bar.sizeHorizontal
    // The rest of what a panel's own bar button and popup ask of a bar,
    // inert here: hosted, neither is ever shown.
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
    function showPage(panel) { root.showPage(panel) }
    function leavePage(panel) { root.leavePage(panel) }
  }

  Item {
    visible: false
    Monitor.Panel { id: displayModule; host: pageHost; bar: pageHost; moduleName: "omarchy.monitor" }
  }
  readonly property var modules: ({ "omarchy.monitor": displayModule })
  readonly property var pageTitles: ({ "omarchy.monitor": Commons.I18n.t("monitor.display") })

  property var page: null
  // 0 on the main view, 1 on the page; the push in between.
  property real pageShift: 0
  NumberAnimation {
    id: pageSlide
    target: root
    property: "pageShift"
    duration: Style.duration(300)
    easing.type: Easing.OutCubic
    onFinished: if (root.pageShift === 0) root.dropPage()
  }

  function showPage(panelForPage) {
    if (!root.opened) root.open()
    if (root.page && root.page !== panelForPage) root.page.hostShown = false
    root.page = panelForPage
    panelForPage.hostShown = true
    pageSlide.to = 1
    pageSlide.restart()
    Qt.callLater(function() { if (pageLoader.item) pageLoader.item.forceActiveFocus() })
  }
  function leavePage(panelForPage) {
    if (root.page !== panelForPage) return
    pageSlide.to = 0
    pageSlide.restart()
    keyCatcher.forceActiveFocus()
  }
  function dropPage() {
    if (root.page) root.page.hostShown = false
    root.page = null
    root.pageShift = 0
  }

  function toggleWifi() { Networking.wifiEnabled = !Networking.wifiEnabled }
  function toggleBluetooth() { if (bluetooth.adapter) bluetooth.adapter.enabled = !bluetooth.adapter.enabled }
  function toggleMic() {
    if (UntypedInput.active) { if (UntypedInput.known) UntypedInput.setMuted(!UntypedInput.muted) }
    else if (source && source.audio) source.audio.muted = !source.audio.muted
  }
  function toggleRotation() { run([omarchy("omarchy-rotation-lock"), rotation.locked ? "off" : "on"]); rotation.locked = !rotation.locked }
  function toggleAwake() { if (idleService) idleService.setIdleEnabled(root.stayAwake) }
  function showKeyboard() { root.close(); run([omarchy("omarchy-keyboard"), "toggle"]) }
  function sessionActions() {
    root.close()
    if (root.shell) root.shell.summon("omarchy.menu", JSON.stringify({ menu: "system" }))
  }
  function setVolume(value) {
    if (sink && sink.audio) sink.audio.volume = Math.max(0, Math.min(1, value))
  }
  function setBrightness(percent) {
    root.brightness = Math.max(1, Math.min(100, Math.round(percent)))
    brightnessSet.restart()
  }

  Timer {
    id: brightnessSet
    interval: 60
    onTriggered: root.run(["omarchy-brightness-display", "--no-osd", root.brightness + "%"])
  }
  Process {
    id: brightnessRead
    command: ["omarchy-brightness-display"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var value = parseInt(text, 10)
        root.brightness = isNaN(value) ? -1 : value
      }
    }
  }
  Process {
    id: autoRead
    command: ["omarchy-auto-brightness", "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.autoBrightness = /auto-brightness: on/.test(text)
    }
  }

  // ------------------------------------------------------------ cells
  // Each focusable cell: kind (tile, slider, toggle, later), what it shows
  // and does. The keyboard walks them in this order, arrows by position.

  readonly property var toggles: [
    { key: "mic", glyph: root.micMuted ? "󰍭" : "󰍬", label: Commons.I18n.t("controlCenter.mic"),
      on: !root.micMuted, enabled: root.micKnown, act: root.toggleMic },
    { key: "rotation", glyph: "󰌾", label: Commons.I18n.t("controlCenter.rotation"),
      on: rotation.locked, enabled: true, act: root.toggleRotation },
    { key: "awake", glyph: "", label: Commons.I18n.t("controlCenter.awake"),
      on: root.stayAwake, enabled: !!root.idleService, act: root.toggleAwake },
    { key: "keyboard", glyph: "󰌌", label: Commons.I18n.t("controlCenter.keyboard"),
      on: false, enabled: true, act: root.showKeyboard }
  ]
  // Live once their backend exists (power profiles, Focus, Night Light, media).
  readonly property var later: [
    { glyph: "󰓅", label: Commons.I18n.t("controlCenter.balanced") },
    { glyph: "󰖔", label: Commons.I18n.t("controlCenter.focus") },
    { glyph: "󰽟", label: Commons.I18n.t("controlCenter.night") },
    { glyph: "󰝚", label: Commons.I18n.t("controlCenter.media") }
  ]

  // Keyboard: the focused cell, or none until the keyboard is used.
  property var focusables: []
  property int focusIndex: -1
  function registerCell(item) {
    var list = root.focusables.slice()
    if (list.indexOf(item) < 0) list.push(item)
    root.focusables = list
  }
  function focusedCell() { return focusIndex >= 0 && focusIndex < focusables.length ? focusables[focusIndex] : null }
  function visibleCells() { return focusables.filter(function(c) { return c && c.visible && c.focusable }) }
  function moveFocus(dx, dy) {
    var cells = visibleCells()
    if (cells.length === 0) return
    var current = focusedCell()
    if (!current || cells.indexOf(current) < 0) { root.focusIndex = focusables.indexOf(cells[0]); return }
    var a = current.mapToItem(card, current.width / 2, current.height / 2)
    var best = null, bestScore = 1e9
    for (var i = 0; i < cells.length; i++) {
      var c = cells[i]
      if (c === current) continue
      var b = c.mapToItem(card, c.width / 2, c.height / 2)
      var along = dx !== 0 ? (b.x - a.x) * dx : (b.y - a.y) * dy
      if (along <= 1) continue
      var across = dx !== 0 ? Math.abs(b.y - a.y) : Math.abs(b.x - a.x)
      var score = along + across * 2
      if (score < bestScore) { bestScore = score; best = c }
    }
    if (best) root.focusIndex = focusables.indexOf(best)
  }
  function stepFocus(delta) {
    var cells = visibleCells()
    if (cells.length === 0) return
    var at = cells.indexOf(focusedCell())
    var next = at < 0 ? (delta > 0 ? 0 : cells.length - 1) : (at + delta + cells.length) % cells.length
    root.focusIndex = focusables.indexOf(cells[next])
  }

  // ----------------------------------------------------------- lifecycle

  function prepare() {
    if (!brightnessRead.running) brightnessRead.running = true
    if (!autoRead.running) autoRead.running = true
    root.focusIndex = -1
  }

  function open() {
    root.prepare()
    root.opened = true
    root.mapped = true
    if (panel.contentRevealed) root.settle(1, 0)
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }
  function close() {
    root.touchSpent = false
    if (!root.opened) return
    root.closingFromOpen = true
    root.opened = false
    root.settle(0, 0)
  }
  function toggle() { root.opened ? root.close() : root.open() }

  // A finger pulls it down from the top edge (the bar), or up to put it
  // away: it follows the finger, past its place only against resistance.
  // Let go, it keeps the finger's speed and a spring carries it to open or
  // back, by how far it came and how fast it was moving.
  property bool pulling: false
  // A long press opened a page while the finger is still down (see above).
  property bool touchSpent: false
  readonly property real pullSpan: Math.max(1, card.y + card.height)
  property real pullFrom: 0

  function beginPull() {
    spring.running = false
    if (!root.opened) {
      root.prepare()
      root.reveal = 0
      root.mapped = true
    }
    root.pullFrom = root.reveal
    root.pulling = true
  }
  function pullTo(distance) {
    if (!root.pulling) return
    var r = root.pullFrom + distance / root.pullSpan
    // Past fully open it gives a little, ever less.
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

  // The spring: reveal moves to its target from the speed it has, slightly
  // underdamped on the way in (it lands, overshoots a touch, settles) and
  // critically damped on the way out (it simply goes).
  property real springTarget: 0
  property real springVelocity: 0
  function settle(target, velocity) {
    root.springTarget = target
    root.springVelocity = velocity
    spring.running = true
  }

  // Going out: closing from open, or a finger pushing it up from open. A
  // pull let go before it opened falls back with the coming-in fade.
  property bool closingFromOpen: false
  readonly property bool leaving: root.pulling ? root.pullFrom > 0.5 : (!root.opened && root.closingFromOpen)
  FrameAnimation {
    id: spring
    onTriggered: {
      // The real time since the last frame, in small fixed steps: a slow
      // frame (software rendering) moves it further rather than slower.
      var elapsed = Math.min(frameTime, 0.25)
      // Softer going out: it is seen to travel up rather than vanish.
      var stiffness = root.springTarget > 0 ? 260 : 195
      var damping = 2 * Math.sqrt(stiffness) * (root.springTarget > 0 ? 0.78 : 1.0)
      var steps = Math.max(1, Math.ceil(elapsed / (1 / 240)))
      var dt = elapsed / steps
      var reveal = root.reveal, velocity = root.springVelocity
      for (var i = 0; i < steps; i++) {
        var force = -stiffness * (reveal - root.springTarget) - damping * velocity
        velocity += force * dt
        reveal += velocity * dt
      }
      root.springVelocity = velocity
      root.reveal = reveal
      if (Math.abs(root.reveal - root.springTarget) < 0.002 && Math.abs(root.springVelocity) < 0.02) {
        root.reveal = root.springTarget
        root.springVelocity = 0
        running = false
        if (!root.opened) { root.mapped = false; root.dropPage() }
      }
    }
  }

  // Moving: the spring or a finger.
  readonly property bool moving: spring.running || root.pulling

  // While open, a note for the Home button (omarchy-home-button closes it).
  readonly property string openNote: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/omarchy-control-center-open"
  onOpenedChanged: Quickshell.execDetached(opened ? ["touch", openNote] : ["rm", "-f", openNote])

  ShellIpc {
    target: "omarchy.controlcenter"
    function toggle(): void { root.toggle() }
    function open(): void { if (!root.opened) root.open() }
    function close(): void { root.close() }
    // Open at a module's page: omarchy.monitor, …
    function page(module: string): void { root.openPage(module) }
  }

  // ------------------------------------------------------------- window

  OverlayWindow {
    id: panel
    shown: root.mapped
    WlrLayershell.namespace: "omarchy-control-center"

    onContentRevealedChanged: if (contentRevealed && root.opened && !root.pulling) {
      root.reveal = 0
      root.settle(1, 0)
      keyCatcher.forceActiveFocus()
    }

    // iPad: the rest of the screen dims, and a tap there closes. Phone: the
    // control center is the screen.
    Rectangle {
      // A phone keeps its status bar above it.
      y: root.phone ? root.barInset : 0
      width: parent.width
      height: parent.height - y
      color: root.phone ? Commons.Color.menu.background : Commons.Color.menu.scrim
      opacity: Math.max(0, Math.min(1, root.reveal))
      MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: root.close()
      }
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true
      Keys.onPressed: function(event) {
        var cell = root.focusedCell()
        switch (event.key) {
        case Qt.Key_Escape: if (root.page) root.leavePage(root.page); else root.close(); break
        case Qt.Key_Tab: root.stepFocus(1); break
        case Qt.Key_Backtab: root.stepFocus(-1); break
        case Qt.Key_Up: root.moveFocus(0, -1); break
        case Qt.Key_Down: root.moveFocus(0, 1); break
        case Qt.Key_Left:
          if (cell && cell.adjust) cell.adjust(-0.05); else root.moveFocus(-1, 0); break
        case Qt.Key_Right:
          if (cell && cell.adjust) cell.adjust(0.05)
          else if (cell && cell.page) root.openPage(cell.page)
          else root.moveFocus(1, 0); break
        case Qt.Key_Return: case Qt.Key_Enter: case Qt.Key_Space:
          if (cell && cell.activate) cell.activate(); break
        default: return
        }
        event.accepted = true
      }
    }

    // A pointer clears the keyboard's highlight.
    PointHandler {
      onActiveChanged: if (active) root.focusIndex = -1
    }

    // Pushed up by a finger, it follows and goes away. Above the card, so it
    // sees every touch; it takes one only once it moves up or down, and a
    // slider keeps its own drags.
    Item {
      anchors.fill: parent
      z: 10
      DragHandler {
        target: null
        xAxis.enabled: false
        acceptedDevices: PointerDevice.TouchScreen
        grabPermissions: PointerHandler.CanTakeOverFromItems | PointerHandler.CanTakeOverFromHandlersOfDifferentType
        enabled: (root.opened || root.pulling) && !root.touchSpent
        onActiveChanged: active ? root.beginPull() : root.endPull(centroid.velocity.y)
        onTranslationChanged: if (active) root.pullTo(translation.y)
      }
      // The touch that held a control until its page opened is spent: once
      // the control lets go of it (its view hides), nothing else takes it.
      // The next touch counts again.
      PointHandler {
        id: anyTouch
        acceptedDevices: PointerDevice.TouchScreen
        onActiveChanged: if (!active) root.touchSpent = false
      }
      // Never stuck: no finger down any more, the touch is over.
      Timer {
        interval: 250
        repeat: true
        running: root.touchSpent
        onTriggered: if (!anyTouch.active) root.touchSpent = false
      }
    }

    // While a touch is spent, it reaches nothing: no hover, press or drag
    // on the page that opened under it, until the finger lifts.
    MouseArea {
      anchors.fill: parent
      z: 20
      visible: root.touchSpent
      hoverEnabled: true
      preventStealing: true
      acceptedButtons: Qt.AllButtons
    }

    BorderSurface {
      id: card
      // While it moves, drawn once into a texture that is only scaled, moved
      // and faded (cheap on any GPU); at rest drawn directly, sharp.
      layer.enabled: root.moving
      layer.smooth: true
      x: root.phone ? 0 : parent.width - width - Style.gapsOut
      y: root.phone ? root.barInset : root.barInset + Style.gapsOut
      width: root.phone ? parent.width : root.cardWidth
      // The main view's height, the page's, and the push between them.
      readonly property real mainHeight: content.implicitHeight + root.pad * 2
      readonly property real pageHeight: pageView.implicitHeight + root.pad * 2
      height: root.phone ? parent.height - root.barInset : mainHeight + (pageHeight - mainHeight) * root.pageShift
      clip: true
      color: root.phone ? "transparent" : Commons.Color.popups.background
      // The bar's popups' own border (KeyboardPanel): the theme's spec.
      borderSpec: root.phone ? Border.none()
        : Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Math.max(1, Style.space(2)))
      radius: Style.cornerRadius
      // Its bottom edge is where the finger is: reveal is the finger's way
      // down as a share of the card's bottom. On the way it grows out of its
      // own top centre and fades in; the slide is what keeps the scaled bottom under the finger.
      readonly property real grow: 0.86 + 0.14 * root.reveal
      transform: [
        Scale {
          origin.x: card.width / 2
          origin.y: 0
          xScale: card.grow
          yScale: card.grow
        },
        Translate { y: root.reveal * root.pullSpan - card.y - card.height * card.grow }
      ]
      // Coming in: solid within the first quarter of the way, most of it at
      // once. Going out (let go to close, or pushed up from open): it fades
      // with its way up, gone as its bottom edge reaches the status bar.
      readonly property real barShare: Math.min(0.9, root.barInset / root.pullSpan)
      opacity: root.leaving
        ? Math.max(0, Math.min(1, (root.reveal - barShare) / (1 - barShare)))
        : 1 - Math.pow(1 - Math.max(0, Math.min(1, root.reveal / 0.25)), 2)

      MouseArea { anchors.fill: parent }  // taps inside never close

      Column {
        id: content
        x: root.pad - root.pageShift * card.width
        visible: root.pageShift < 1
        y: root.pad + (root.phone ? Style.space(12) : 0)
        width: parent.width - root.pad * 2
        spacing: root.gap

        // Wi-Fi and Bluetooth.
        Row {
          spacing: root.gap
          Tile {
            width: (content.width - root.gap) / 2
            glyph: network.icon !== "" ? network.icon : "󰖪"
            title: Commons.I18n.t("controlCenter.wifi")
            subtitle: root.wifiSubtitle
            on: network.wifiEnabled
            page: "omarchy.network"
            onActivated: root.toggleWifi()
          }
          Tile {
            width: (content.width - root.gap) / 2
            glyph: bluetooth.icon !== "" ? bluetooth.icon : "󰂲"
            title: Commons.I18n.t("controlCenter.bluetooth")
            subtitle: root.bluetoothSubtitle
            on: bluetooth.enabled
            available: !!bluetooth.adapter
            page: "omarchy.bluetooth"
            onActivated: root.toggleBluetooth()
          }
        }

        // Brightness and volume: one full-width row each, a phone's taller.
        Grid {
          columns: 1
          spacing: root.gap
          Slider {
            width: content.width
            height: Style.space(root.phone ? 48 : 44)
            vertical: false
            glyph: "󰃞"
            value: root.brightness < 0 ? 0 : root.brightness / 100
            available: root.brightness >= 0
            note: root.autoBrightness ? Commons.I18n.t("controlCenter.auto") : ""
            pageArrow: true
            onMoved: function(v) { root.setBrightness(v * 100) }
            onLongPressed: root.openPage("omarchy.monitor")
          }
          Slider {
            width: content.width
            height: Style.space(root.phone ? 48 : 44)
            vertical: false
            glyph: root.volume <= 0 || (root.sink && root.sink.audio && root.sink.audio.muted) ? "󰝟" : "󰕾"
            value: root.volume
            available: !!(root.sink && root.sink.audio)
            chip: root.outputName
            onMoved: function(v) { root.setVolume(v) }
            onLongPressed: root.openPage("omarchy.audio")
          }
        }

        // The toggles, then the ones still to come.
        Grid {
          columns: 4
          spacing: root.gap
          Repeater {
            model: root.toggles
            Toggle {
              required property var modelData
              width: (content.width - root.gap * 3) / 4
              height: root.phone ? width : Style.space(64)
              glyph: modelData.glyph
              label: modelData.label
              on: modelData.on
              available: modelData.enabled
              onActivated: modelData.act()
            }
          }
          Repeater {
            model: root.later
            Toggle {
              required property var modelData
              width: (content.width - root.gap * 3) / 4
              height: root.phone ? width : Style.space(64)
              glyph: modelData.glyph
              label: modelData.label
              available: false
            }
          }
        }

        // Battery line and the session actions (iPad: here; phone: at the foot).
        Item {
          id: footer
          width: content.width
          height: root.touchMin
          visible: !root.phone
          FooterParts { anchors.fill: parent }
        }
      }

      Item {
        visible: root.phone && root.pageShift < 1
        x: root.pad - root.pageShift * card.width
        width: parent.width - root.pad * 2
        height: root.touchMin
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.space(24)
        FooterParts { anchors.fill: parent }
      }

      // The page: a header with the way back, then the panel's content.
      Column {
        id: pageView
        visible: root.page !== null
        x: root.pad + (1 - root.pageShift) * card.width
        y: root.pad + (root.phone ? Style.space(12) : 0)
        width: parent.width - root.pad * 2
        spacing: root.gap

        Item {
          width: parent.width
          height: root.touchMin
          Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(8)
            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "󰁍"
              color: root.text
              font.family: Style.font.family
              font.pixelSize: Style.font.title
            }
            Text {
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.page ? (root.pageTitles[root.page.moduleName] || "") : ""
              color: root.text
              font.family: Style.font.family
              font.pixelSize: Style.font.title
              font.bold: true
            }
          }
          MouseArea {
            width: Math.max(root.touchMin, parent.width / 2)
            height: parent.height
            onClicked: if (root.page) root.leavePage(root.page)
          }
        }

        Loader {
          id: pageLoader
          width: parent.width
          active: root.page !== null
          sourceComponent: root.page ? root.page.pageContent : null
          // As tall as its content, within the screen; the content scrolls
          // beyond that.
          readonly property real header: root.touchMin + root.gap
          readonly property real room: root.screenHeight - card.y - root.pad * 2 - header - Style.gapsOut
          height: item ? Math.min(item.implicitHeight, root.phone ? card.height - root.pad * 2 - header - Style.space(12) : room) : 0
        }
      }
    }
  }

  // ----------------------------------------------------------- components

  component Cell: Rectangle {
    id: cell
    property bool on: false
    property bool available: true
    property string page: ""
    property bool focusable: available
    readonly property bool focused: root.focusables[root.focusIndex] === cell
    property bool pressed: false
    signal activated()
    function activate() { if (cell.available) cell.activated() }
    Component.onCompleted: root.registerCell(cell)
    radius: Style.cornerRadius
    color: !available ? "transparent"
      : (on ? root.onFill : Style.controlFill(false, false, root.text, Commons.Color.accent))
    // Pressed, it only shrinks a little: no tint.
    scale: pressed ? 0.96 : 1
    Behavior on scale { NumberAnimation { duration: Style.duration(120); easing.type: Easing.OutCubic } }
    border.width: Math.max(1, Style.space(1))
    border.color: focused ? Commons.Color.accent : (on && available ? root.onFill : Style.normalBorderColor)
    opacity: available ? 1 : 0.45
  }

  component Tile: Cell {
    id: tile
    pressed: tileMouse.pressed && tileMouse.containsMouse
    property string glyph: ""
    property string title: ""
    property string subtitle: ""
    height: root.phone ? Style.space(64) : Style.space(56)
    readonly property color ink: on && available ? root.onText : root.text
    Row {
      x: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(10)
      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: tile.glyph
        color: tile.ink
        font.family: Style.font.family
        font.pixelSize: Style.font.title
      }
      Column {
        anchors.verticalCenter: parent.verticalCenter
        width: tile.width - Style.space(12) * 2 - Style.space(10) - Style.font.title - (tile.page !== "" && !root.phone ? Style.space(20) : 0)
        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: tile.title
          color: tile.ink
          font.family: Style.font.family
          font.pixelSize: Style.font.subtitle
          font.bold: true
          elide: Text.ElideRight
        }
        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: tile.subtitle
          color: tile.ink
          opacity: 0.75
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
    // Tap toggles; a right click opens the page. Held still (0.2 s), the
    // touch arms the page as on a slider: the tile shows it is held, lifting
    // opens the page, sliding off cancels. One rule for every control: a tap
    // never opens another level.
    MouseArea {
      id: tileMouse
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      pressAndHoldInterval: 200
      // A button keeps its touch: sliding off cancels, and the control center
      // is not dragged away.
      preventStealing: true
      property bool held: false
      property bool used: false
      readonly property bool holding: held && containsMouse
      // Held on armed a while longer, it opens without waiting for the lift.
      Timer {
        id: tileHoldOpen
        interval: 600
        onTriggered: if (tileMouse.holding) {
          tileMouse.held = false
          tileMouse.used = true
          root.touchSpent = true
          root.openPage(tile.page)
        }
      }
      onPressed: { held = false; used = false }
      onReleased: {
        tileHoldOpen.stop()
        if (!used && held && containsMouse && tile.page) root.openPage(tile.page)
        held = false
      }
      onCanceled: { held = false; used = false; tileHoldOpen.stop() }
      onPressAndHold: if (tile.page) { held = true; tileHoldOpen.restart() }
      onClicked: function(mouse) {
        if (held || used) return
        if (mouse.button === Qt.RightButton) { if (tile.page) root.openPage(tile.page) }
        else tile.activate()
      }
    }
    Item {
      visible: tile.page !== "" && !root.phone
      anchors.right: parent.right
      width: Style.space(32)
      height: parent.height
      Text {
        anchors.centerIn: parent
        text: "󰅂"
        color: tileMouse.holding ? Commons.Color.accent : tile.ink
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
      // A hint only: a tap toggles anywhere on the tile, a long press (or a
      // right click) opens the page.
    }
  }

  component Toggle: Cell {
    id: toggle
    property string glyph: ""
    property string label: ""
    readonly property color ink: on && available ? root.onText : root.text
    Column {
      anchors.centerIn: parent
      spacing: Style.space(4)
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: toggle.glyph
        color: toggle.ink
        font.family: Style.font.family
        font.pixelSize: Style.font.iconLarge
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: toggle.label
        color: toggle.ink
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }
    }
    // A button keeps its touch: sliding off cancels (the press look goes),
    // sliding back on arms it again; the control center is not dragged.
    pressed: toggleMouse.pressed && toggleMouse.containsMouse
    MouseArea {
      id: toggleMouse
      anchors.fill: parent
      enabled: toggle.available
      preventStealing: true
      onClicked: toggle.activate()
    }
  }

  // A level you drag: the filled part is the value. Horizontal on an iPad,
  // vertical (bottom up) on a phone. A long press opens the module's page.
  component Slider: Cell {
    id: slider
    property bool vertical: false
    property string glyph: ""
    property real value: 0
    property string note: ""
    property string chip: ""
    // A page with no chip of its own shows the arrow alone.
    property bool pageArrow: false
    signal moved(real value)
    signal longPressed()
    // Left and right move it; Enter opens its page.
    onActivated: slider.longPressed()
    function adjust(delta) { if (slider.available) slider.moved(Math.max(0, Math.min(1, slider.value + delta))) }
    color: Style.controlFill(false, false, root.text, Commons.Color.accent)
    clip: true
    scale: drag.holding ? 0.96 : 1
    Behavior on scale { NumberAnimation { duration: Style.duration(140); easing.type: Easing.OutCubic } }

    Rectangle {
      x: 0
      y: slider.vertical ? parent.height * (1 - slider.value) : 0
      width: slider.vertical ? parent.width : parent.width * slider.value
      height: slider.vertical ? parent.height * slider.value : parent.height
      color: root.text
      opacity: 0.85
    }

    Text {
      x: slider.vertical ? (parent.width - width) / 2 : Style.space(12)
      y: slider.vertical ? parent.height - height - Style.space(12) : (parent.height - height) / 2
      text: slider.glyph
      color: slider.value > 0.08 ? Commons.Color.background : root.text
      font.family: Style.font.family
      font.pixelSize: Style.font.title
    }
    Text {
      visible: slider.note !== ""
      // Left of the chip, which takes the right end.
      x: slider.vertical ? Style.space(12)
        : parent.width - width - Style.space(12) - (chipBox.visible ? chipBox.width + Style.space(8) : 0)
      y: slider.vertical ? Style.space(12) : (parent.height - height) / 2
      textFormat: Text.PlainText
      text: slider.note
      color: root.text
      opacity: 0.7
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
    MouseArea {
      id: drag
      anchors.fill: parent
      enabled: slider.available
      preventStealing: true
      // The level goes where the finger is: on a tap when it lifts, on a
      // drag as soon as it moves and from then on. Held still (0.2 s), the
      // touch arms the page instead and changes nothing: the slider shows it
      // is held, lifting opens the page, sliding off cancels (and back on
      // arms it again). Nothing happens on the touch itself before it is
      // known which it is.
      pressAndHoldInterval: 200
      property point pressedAt
      property bool moving: false
      property bool held: false
      // The page opened by holding on: the rest of the touch does nothing.
      property bool used: false
      readonly property bool holding: held && containsMouse
      // Held on armed a while longer, it opens without waiting for the lift.
      Timer {
        id: sliderHoldOpen
        interval: 600
        onTriggered: if (drag.holding) { drag.held = false; drag.used = true; root.touchSpent = true; slider.longPressed() }
      }
      function valueAt(mouse) {
        return Math.max(0, Math.min(1, slider.vertical ? 1 - mouse.y / slider.height : mouse.x / slider.width))
      }
      onPressed: function(mouse) {
        pressedAt = Qt.point(mouse.x, mouse.y)
        moving = false
        held = false
        used = false
      }
      onPositionChanged: function(mouse) {
        if (!pressed || used) return
        var along = slider.vertical ? Math.abs(mouse.y - pressedAt.y) : Math.abs(mouse.x - pressedAt.x)
        var across = slider.vertical ? Math.abs(mouse.x - pressedAt.x) : Math.abs(mouse.y - pressedAt.y)
        if (held) {
          // Armed, a move along the slider disarms it and drags after all;
          // off it the other way only cancels (containsMouse).
          if (along <= Style.space(10) || along < across) return
          held = false
          sliderHoldOpen.stop()
        } else if (!moving && along + across <= Style.space(10)) return
        moving = true
        slider.moved(valueAt(mouse))
      }
      onReleased: function(mouse) {
        sliderHoldOpen.stop()
        if (used) { used = false; return }
        if (held) { if (containsMouse) slider.longPressed() }
        else if (!moving) slider.moved(valueAt(mouse))
        held = false
      }
      onCanceled: { held = false; used = false; sliderHoldOpen.stop() }
      onPressAndHold: if (!moving) { held = true; sliderHoldOpen.restart() }
    }
    Rectangle {
      id: chipBox
      // The way to the slider's page, always in sight: a named chip (the
      // output) or the arrow alone. While a long press holds the slider, it
      // lights up: lifting goes there.
      visible: slider.chip !== "" || slider.pageArrow
      x: slider.vertical && slider.chip !== "" ? Style.space(10) : parent.width - width - Style.space(10)
      y: slider.vertical ? Style.space(10) : (parent.height - height) / 2
      width: Math.min(chipRow.implicitWidth + Style.space(16), parent.width - Style.space(20))
      height: Style.space(26)
      // The arrow alone is only a glyph in the slider's own ink: dark on the
      // fill, light beside it.
      readonly property bool arrowOnly: slider.chip === ""
      readonly property bool onFillPart: slider.vertical
        ? (1 - (y + height / 2) / slider.height) < slider.value
        : (x + width / 2) / slider.width < slider.value
      readonly property color ink: drag.holding
        ? (arrowOnly ? Commons.Color.accent : root.onText)
        : (arrowOnly && onFillPart ? Commons.Color.background : root.text)
      color: arrowOnly ? "transparent" : (drag.holding ? root.onFill : Commons.Color.popups.background)
      border.width: arrowOnly ? 0 : Math.max(1, Style.space(1))
      border.color: drag.holding ? root.onFill : Style.normalBorderColor
      radius: Style.cornerRadius
      Row {
        id: chipRow
        anchors.centerIn: parent
        spacing: Style.space(6)
        Text {
          visible: slider.chip !== ""
          width: Math.min(implicitWidth, chipBox.parent.width - Style.space(48))
          textFormat: Text.PlainText
          text: slider.chip
          color: chipBox.ink
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
          elide: Text.ElideRight
        }
        Text {
          text: "󰅂"
          color: chipBox.ink
          opacity: chipBox.arrowOnly && !drag.holding ? 0.7 : 1
          font.family: Style.font.family
          font.pixelSize: chipBox.arrowOnly ? Style.font.body : Style.font.caption
        }
      }
      // Only a hint that there is a page: a long press opens it, and a tap
      // here sets the level like anywhere else on the slider.
    }
  }

  component FooterParts: Item {
    // Battery line: opens the battery page; the power button the session.
    Cell {
      id: batteryCell
      visible: root.batteryLine !== ""
      page: "omarchy.power"
      color: "transparent"
      border.width: focused ? Math.max(1, Style.space(1)) : 0
      width: batteryRow.implicitWidth + Style.space(16)
      height: parent.height
      onActivated: root.openPage("omarchy.power")
      Row {
        id: batteryRow
        x: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(6)
        Text { anchors.verticalCenter: parent.verticalCenter; text: battery.icon; color: root.text; font.family: Style.font.family; font.pixelSize: Style.font.body }
        Text { anchors.verticalCenter: parent.verticalCenter; textFormat: Text.PlainText; text: root.batteryLine; color: root.text; font.family: Style.font.family; font.pixelSize: Style.font.caption }
        Text { anchors.verticalCenter: parent.verticalCenter; text: "󰅂"; color: root.text; opacity: 0.6; font.family: Style.font.family; font.pixelSize: Style.font.caption }
      }
      MouseArea { anchors.fill: parent; onClicked: batteryCell.activate() }
    }
    Cell {
      id: powerCell
      anchors.right: parent.right
      width: root.touchMin
      height: parent.height
      color: "transparent"
      border.width: focused ? Math.max(1, Style.space(1)) : 0
      onActivated: root.sessionActions()
      Text {
        anchors.centerIn: parent
        text: "󰐥"
        color: Commons.Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.title
      }
      MouseArea { anchors.fill: parent; onClicked: powerCell.activate() }
    }
  }
}
