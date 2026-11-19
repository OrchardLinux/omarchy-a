import QtQuick
import QtQuick.Effects
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "../status" as Status

Item {
  id: root

  property string backgroundPath: ""
  property string videoPosterPath: ""
  property int backgroundVersion: 0
  property bool fingerprintConfigured: false
  property bool fingerprintUnavailable: false
  property bool authenticatingPassword: false
  property string failureMessage: ""
  property int failedAttempts: 0
  property bool inputEnabled: true
  property bool loadBackground: true
  property string passwordText: ""
  // Stay Awake, for the status cluster (the shell's idle service knows it).
  property bool stayAwake: false
  property bool syncingPasswordText: false

  readonly property bool touchPin: Quickshell.env("OMARCHY_TOUCH_MODE") === "1"
  readonly property string placeholderText: Commons.I18n.t("lock.enterPassword")
  readonly property int fieldWidth: Math.min(Style.space(phone ? 306 : 372), Math.max(1, width - 48))
  readonly property int fieldHeight: touchPin ? 0 : Style.space(phone ? 52 : 60)
  readonly property int outlineThickness: 3
  readonly property int fieldFontSize: Style.space(phone ? 16 : 18)
  readonly property int passwordDotFontSize: Math.round(Style.font.heading * 1.33)
  readonly property int passwordDotLetterSpacing: Math.round(Style.font.heading * 0.19)
  // Space to keep clear on each side of the field for the fingerprint icon
  // (icon width plus a gap) so the centered dots never run under it.
  readonly property real fingerprintReserve: fingerprintConfigured ? Math.round(fingerprintIcon.implicitWidth + 12) : 0
  // Shrink the dots to fit once the password outgrows the field, so every
  // keystroke stays visible — otherwise long passwords clip with no feedback.
  readonly property real passwordDotScale: dotMetrics.advanceWidth > 0
    ? Math.min(1, (passwordInput.width - 4) / dotMetrics.advanceWidth)
    : 1
  readonly property bool showPasswordCursor: inputEnabled && !authenticatingPassword && failureMessage.length === 0
  readonly property bool errorState: failureMessage.length > 0
  readonly property var inputBorderSpec: errorState
    ? Border.surfaceSpec("lock", "border-error", Commons.Color.lock.borderError, root.outlineThickness, "border-alpha")
    : Border.surfaceSpec("lock", "border-active", Commons.Color.lock.borderActive, root.outlineThickness, "border-alpha")

  // Layout (expose.pen, "Lock — PIN"): the clock above the PIN, or beside
  // it in landscape; a phone's own sizes. Points, scaled like the shell.
  readonly property bool phone: Math.min(width, height) < 600
  readonly property bool landscape: width > height
  readonly property var metrics: phone
    ? { lockIcon: 16, time: 72, date: 14, slot: 12, slotGap: 14, slotRow: 24, message: 28, gap: 12,
        keyWidth: 64, keyHeight: landscape ? 46 : 52, keyGap: 10, keyColumnGap: 36, digit: 28, backspace: 24, failure: 13, between: landscape ? 48 : 36, stack: landscape ? 28 : 36 }
    : { lockIcon: 18, time: landscape ? 112 : 120, date: 18, slot: 14, slotGap: 18, slotRow: 24, message: 40, gap: 16,
        keyWidth: 72, keyHeight: 56, keyGap: 18, keyColumnGap: 48, digit: 34, backspace: 28, failure: 15, between: landscape ? 120 : 56, stack: 56 }
  function pt(name) { return Style.space(root.metrics[name]) }
  readonly property bool pinBusy: !root.inputEnabled || root.authenticatingPassword
  // A wrong PIN is drawn in the theme's red: some themes (Tokyo Night) give
  // the lock's error text their plain foreground.
  readonly property color failureColor: Commons.Color.urgent
  // A soft shadow in the theme's background under the clock, the slots and
  // the failure: readable on any wallpaper without darkening all of it. The
  // GPU draws it; software rendering goes without.
  readonly property bool gpu: Quickshell.env("QT_QUICK_BACKEND") !== "software"
  component Shade: MultiEffect {
    shadowEnabled: true
    shadowColor: Commons.Color.background
    shadowOpacity: 0.55
    shadowBlur: 1.0
    blurMax: 64
    shadowHorizontalOffset: 0
    shadowVerticalOffset: 0
    autoPaddingEnabled: true
  }

  property date now: new Date()
  Timer {
    interval: 1000
    repeat: true
    running: root.visible
    triggeredOnStart: true
    onTriggered: root.now = new Date()
  }

  // A video wallpaper shows its still poster: nothing plays behind the lock.
  readonly property bool video: Util.isVideoPath(root.backgroundPath)
  // Orchard: lets the greeter appear with its wallpaper drawn (greeter/shell.qml).
  readonly property bool backgroundDrawn: !root.loadBackground || wallpaper.ready || wallpaper.failed

  signal submitPassword(string password)
  signal passwordTextEdited(string password)
  signal clearFailureRequested()
  signal wakeRequested()

  function forcePasswordFocus() {
    passwordInput.forceActiveFocus()
  }

  function clearPassword() {
    passwordTextEdited("")
  }

  // Only the surface receiving user input submits. Mirrored lock surfaces
  // share passwordText, but must not each submit when that binding changes.
  function editPin(value) {
    if (!inputEnabled || authenticatingPassword) return
    var pin = String(value).replace(/[^0-9]/g, "").slice(0, 6)
    passwordTextEdited(pin)
    syncPasswordText()
    if (pin.length === 6) {
      passwordTextEdited("")
      submitPassword(pin)
    }
  }

  // Waking a DPMS-blanked display can stall the compositor for seconds while
  // the monitor modesets, so the wake key's release arrives late and client-side
  // key repeat floods the field with that character. A held key has no business
  // typing a password; only holding Backspace/Delete to clear stays useful.
  function dropsAutoRepeat(key) {
    return key !== Qt.Key_Backspace && key !== Qt.Key_Delete
  }

  function syncPasswordText() {
    if (passwordInput.text === passwordText) return
    syncingPasswordText = true
    passwordInput.text = passwordText
    syncingPasswordText = false
  }

  // The field loses focus while a password is checked (it is disabled then),
  // and forcing focus onto it would not stick until the check ends.
  function restorePasswordFocus() {
    if (inputEnabled && passwordInput.enabled && !passwordInput.activeFocus) forcePasswordFocus()
  }

  onPasswordTextChanged: syncPasswordText()
  onInputEnabledChanged: {
    if (inputEnabled) Qt.callLater(forcePasswordFocus)
  }

  // A VT switch, which the NVIDIA driver forces around every suspend, takes the
  // keyboard away and Qt drops the field's focus with it. Nothing gives it back
  // when the keyboard returns, so typing went nowhere until the field was clicked.
  Window.onActiveFocusItemChanged: Qt.callLater(restorePasswordFocus)
  Component.onCompleted: {
    syncPasswordText()
    if (inputEnabled) Qt.callLater(forcePasswordFocus)
  }

  // Measures the masked password at full size; passwordDotScale compares this
  // against the field width to decide how far the dots must shrink to fit.
  TextMetrics {
    id: dotMetrics
    font.family: Style.font.family
    font.pixelSize: root.passwordDotFontSize
    font.letterSpacing: root.passwordDotLetterSpacing
    text: "●".repeat(passwordInput.text.length)
  }

  Rectangle {
    anchors.fill: parent
    color: Commons.Color.background

    BackgroundMedia {
      id: wallpaper
      objectName: "lockWallpaper"
      anchors.fill: parent
      path: root.loadBackground ? (root.video ? root.videoPosterPath : root.backgroundPath) : ""
      version: root.backgroundVersion
      // Decode only once sized, at the lock's own size: an unsized first
      // request decoded the file at its native resolution, then again once
      // sized. That size is what the lock service keeps decoded ahead of the
      // lock, so the first frame has the wallpaper.
      cached: true
      constrainDecode: true
      decodeSize: Qt.size(width, height)
    }

    // The wallpaper stays sharp under a dark gradient, light behind the
    // clock so the wallpaper shows and dark behind the keypad so bare digits
    // read on a bright one: down the screen in portrait, across it towards
    // the keypad's side in landscape. Its light end is the theme's
    // lock.scrim; the rest is the theme background.
    Rectangle {
      id: shade
      anchors.fill: parent
      readonly property bool across: root.landscape
      // Right to left, the keypad is on the left.
      readonly property bool reversed: across && Commons.I18n.rightToLeft
      gradient: Gradient {
        orientation: shade.across ? Gradient.Horizontal : Gradient.Vertical
        GradientStop { position: 0.0; color: shade.reversed ? Util.alpha(Commons.Color.background, 0.95) : Commons.Color.lock.scrim }
        GradientStop { position: shade.reversed ? 0.4 : 0.35; color: Util.alpha(Commons.Color.background, shade.reversed ? 0.9 : 0.6) }
        GradientStop { position: shade.reversed ? 0.65 : 0.6; color: Util.alpha(Commons.Color.background, shade.reversed ? 0.6 : 0.9) }
        GradientStop { position: 1.0; color: shade.reversed ? Commons.Color.lock.scrim : Util.alpha(Commons.Color.background, 0.95) }
      }
    }

    // The status bar's right-hand cluster only: no logo (the launcher is not
    // reachable while locked) and no clock (the big one shows the time).
    Status.StatusCluster {
      // Centred in the status bar's 24-point band.
      y: Math.round((Style.space(24) - height) / 2)
      anchors.right: parent.right
      anchors.rightMargin: Style.space(root.phone ? 12 : 16)
      stayAwake: root.stayAwake
      color: Commons.Color.lock.text
    }

    MouseArea {
      anchors.fill: parent
      // Creating a lock surface can synthesize a pointer movement. On a tablet
      // that is not a wake gesture and must not undo Power's immediate blank.
      hoverEnabled: !root.touchPin
      onClicked: { root.wakeRequested(); root.forcePasswordFocus() }
      onPositionChanged: if (!root.touchPin) root.wakeRequested()
    }

    // Below the status bar's height, the clock and the PIN, centred; scaled
    // down only where a screen is too small for them (a phone on its side).
    Item {
      id: content
      anchors.fill: parent
      anchors.topMargin: Style.space(24)
      anchors.bottomMargin: Style.space(root.phone ? 16 : 24)
      anchors.leftMargin: Style.space(root.phone ? 16 : 24)
      anchors.rightMargin: anchors.leftMargin

      Grid {
        id: layout
        anchors.centerIn: parent
        columns: root.landscape ? 2 : 1
        rowSpacing: root.pt("between")
        columnSpacing: root.pt("between")
        verticalItemAlignment: Grid.AlignVCenter
        horizontalItemAlignment: root.landscape ? Grid.AlignLeft : Grid.AlignHCenter
        scale: Math.min(1, content.width / Math.max(1, implicitWidth), content.height / Math.max(1, implicitHeight))

        // ------------------------------------------------------ clock
        Column {
          id: clockBlock
          layer.enabled: root.gpu
          layer.effect: Shade {}
          spacing: Style.space(6)
          // x, not an anchor: an anchor let go on rotation keeps its place.

          Text {
            x: root.landscape ? 0 : (parent.width - width) / 2
            text: "󰍁"
            color: Commons.Color.lock.text
            font.family: Style.font.family
            font.pixelSize: root.pt("lockIcon")
          }
          Text {
            id: clockTime
            x: root.landscape ? 0 : (parent.width - width) / 2
            textFormat: Text.PlainText
            text: Qt.formatTime(root.now, "HH:mm")
            color: Commons.Color.lock.text
            font.family: Style.font.family
            font.pixelSize: root.pt("time")
            font.bold: true
            lineHeight: 0.92
          }
          Text {
            x: root.landscape ? 0 : (parent.width - width) / 2
            textFormat: Text.PlainText
            text: Qt.locale().toString(root.now, "dddd, d MMMM")
            color: Commons.Color.lock.text
            font.family: Style.font.family
            font.pixelSize: root.pt("date")
          }
        }

        // -------------------------------------------------------- PIN
        Column {
          id: pinBlock
          width: root.touchPin ? keypad.width : root.fieldWidth
          // With the keypad, the failure line is the space between slots and
          // keys; the field in password mode keeps its gap.
          spacing: root.touchPin ? 0 : root.pt("gap")

          // The slots and failure (entry, below).
          Item {
            id: pinEntry
            width: parent.width
            height: entry.height
          }

          // Password mode: the field, restyled to the keys' surface.
          BorderSurface {
            id: inputField
            width: root.fieldWidth
            height: root.fieldHeight
            anchors.horizontalCenter: parent.horizontalCenter
            color: root.touchPin ? "transparent" : Commons.Color.lock.background
            borderSpec: root.touchPin ? Border.none() : root.inputBorderSpec
            radius: Style.cornerRadius
            clip: true
            opacity: root.touchPin ? 0 : 1

            TextInput {
              id: passwordInput
              anchors.fill: parent
              anchors.topMargin: inputField.borderTop
              // Reserve the fingerprint icon's width on both sides so the centered
              // dots stay symmetric and never slide under the icon as they grow.
              anchors.rightMargin: inputField.borderRight + 18 + root.fingerprintReserve
              anchors.bottomMargin: inputField.borderBottom
              anchors.leftMargin: inputField.borderLeft + 18 + root.fingerprintReserve
              verticalAlignment: TextInput.AlignVCenter
              horizontalAlignment: TextInput.AlignHCenter
              activeFocusOnPress: true
              clip: true
              enabled: root.inputEnabled && !root.authenticatingPassword
              readOnly: root.authenticatingPassword
              maximumLength: root.touchPin ? 6 : 32767
              inputMethodHints: root.touchPin ? Qt.ImhDigitsOnly | Qt.ImhNoPredictiveText | Qt.ImhSensitiveData : Qt.ImhSensitiveData
              echoMode: TextInput.Password
              passwordCharacter: "●"
              passwordMaskDelay: 0
              color: Commons.Color.lock.text
              selectionColor: Commons.Color.lock.selection
              selectedTextColor: Commons.Color.lock.text
              font.family: Style.font.family
              font.pixelSize: text.length > 0 ? Math.max(1, Math.floor(root.passwordDotFontSize * root.passwordDotScale)) : root.fieldFontSize
              font.letterSpacing: text.length > 0 ? root.passwordDotLetterSpacing * root.passwordDotScale : 0
              cursorVisible: activeFocus && root.showPasswordCursor && text.length > 0
              cursorDelegate: Rectangle {
                width: 2
                color: Commons.Color.accent
                visible: passwordInput.cursorVisible
              }

              onTextChanged: {
                if (!root.syncingPasswordText) {
                  if (root.touchPin) root.editPin(text)
                  else root.passwordTextEdited(text)
                }
                if (text.length > 0) {
                  root.wakeRequested()
                }
                if (text.length > 0 && root.failureMessage.length > 0) root.clearFailureRequested()
              }

              onAccepted: {
                if (root.touchPin) return
                var submitted = root.passwordText
                root.passwordTextEdited("")
                if (submitted.length > 0) root.submitPassword(submitted)
              }

              Keys.onPressed: function(event) {
                // A held key is one press. Its repeats are not new activity: a key
                // whose release went missing would otherwise keep the screen awake
                // and the shell busy until something moved keyboard focus.
                if (!event.isAutoRepeat) root.wakeRequested()
                if (event.isAutoRepeat && root.dropsAutoRepeat(event.key)) {
                  event.accepted = true
                  return
                }
                if (event.key === Qt.Key_Escape || (event.modifiers & Qt.ControlModifier && event.key === Qt.Key_U)) {
                  root.passwordTextEdited("")
                  event.accepted = true
                }
              }
            }

            Text {
              textFormat: Text.PlainText
              anchors.fill: passwordInput
              text: root.authenticatingPassword ? Commons.I18n.t("lock.checking") : root.placeholderText
              visible: !root.touchPin && passwordInput.text.length === 0
              color: Commons.Color.lock.placeholder
              font.family: Style.font.family
              font.pixelSize: root.fieldFontSize
              horizontalAlignment: Text.AlignHCenter
              verticalAlignment: Text.AlignVCenter
              elide: Text.ElideRight
            }

            // Fingerprint hint pinned inside the field's right edge when a sensor is
            // enrolled, so the user knows they can touch to unlock instead of typing.
            // Matches hyprlock, which draws its fingerprint icon in the same spot.
            // A reader the shell cannot reach crosses out rather than disappears, so
            // it stops inviting touches that can never unlock.
            Text {
              id: fingerprintIcon
              objectName: "fingerprintIndicator"
              textFormat: Text.PlainText
              anchors.right: parent.right
              anchors.rightMargin: inputField.borderRight + 18
              anchors.verticalCenter: parent.verticalCenter
              visible: !root.touchPin && root.fingerprintConfigured
              text: root.fingerprintUnavailable ? "󰺱" : "󰈷"
              color: root.fingerprintUnavailable ? Commons.Color.lock.textError : Commons.Color.lock.placeholder
              font.family: Style.font.family
              font.pixelSize: Math.round(root.fieldFontSize * 1.1)
              horizontalAlignment: Text.AlignHCenter
              verticalAlignment: Text.AlignVCenter
            }
          }

          // The shell's own keypad: the on-screen keyboard is not used here.
          Grid {
            id: keypad
            visible: root.touchPin
            columns: 3
            rowSpacing: root.pt("keyGap")
            columnSpacing: root.pt("keyColumnGap")
            Repeater {
              model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"]
              // A bare digit in a full cell, nothing drawn around it at rest;
              // pressed, a faint square behind it. Backspace the same.
              Item {
                id: pinKey
                required property string modelData
                readonly property bool backspaceKey: modelData === "⌫"
                width: root.pt("keyWidth")
                height: root.pt("keyHeight")
                opacity: modelData === "" ? 0 : (root.pinBusy ? 0.55 : 1)

                Rectangle {
                  anchors.fill: parent
                  radius: Style.cornerRadius
                  visible: pinMouse.pressed
                  color: Util.alpha(Commons.Color.lock.text, 0.12)
                }
                Text {
                  anchors.centerIn: parent
                  textFormat: Text.PlainText
                  text: pinKey.backspaceKey ? "󰭜" : pinKey.modelData
                  color: Commons.Color.lock.text
                  font.family: Style.font.family
                  font.pixelSize: pinKey.backspaceKey ? root.pt("backspace") : root.pt("digit")
                }
                MouseArea {
                  id: pinMouse
                  anchors.fill: parent
                  enabled: pinKey.modelData !== "" && !root.pinBusy
                  onClicked: {
                    root.wakeRequested()
                    if (pinKey.backspaceKey) root.editPin(root.passwordText.slice(0, -1))
                    else if (root.passwordText.length < 6) {
                      root.clearFailureRequested()
                      root.editPin(root.passwordText + pinKey.modelData)
                    }
                    root.forcePasswordFocus()
                  }
                }
              }
            }
          }
        }
      }

      // Slots and failure, above the keys.
      Column {
        id: entry
        parent: pinEntry
        width: pinBlock.width

        // Six slots, filled as digits come; outlined in red after a miss.
        Item {
          visible: root.touchPin
          width: parent.width
          height: root.pt("slotRow")
          layer.enabled: root.gpu
          layer.effect: Shade {}
          Row {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            spacing: root.pt("slotGap")
            Repeater {
              model: 6
              Rectangle {
                required property int index
                // The PIN itself is cleared on submit; its slots stay filled
                // until the check finishes.
                readonly property bool filled: !root.errorState && (root.authenticatingPassword || index < root.passwordText.length)
                width: root.pt("slot")
                height: width
                radius: Math.min(Style.cornerRadius, width / 2)
                color: filled ? Commons.Color.lock.text : "transparent"
                border.width: filled ? 0 : Math.max(1, Style.space(1.5))
                border.color: root.errorState ? root.failureColor : Commons.Color.lock.placeholder
              }
            }
          }
        }

        // The failure, between the slots and the keys (above the field in
        // password mode). Its space is kept when empty, so nothing moves.
        Text {
          id: failureLine
          objectName: "lockFailure"
          layer.enabled: root.gpu && text.length > 0
          layer.effect: Shade {}
          width: parent.width
          // Above the keys, the line is the gap to them: as wide as the one
          // from the date to the slots, so the screen is balanced without a
          // failure, and one appears inside it without moving anything.
          height: root.touchPin ? root.pt("stack") : root.pt("message")
          textFormat: Text.PlainText
          text: root.errorState ? root.failureMessage
            : (root.fingerprintConfigured && root.fingerprintUnavailable && !root.touchPin ? Commons.I18n.t("lock.fingerprintUnavailable") : "")
          color: root.failureColor
          font.family: Style.font.family
          font.pixelSize: root.pt("failure")
          font.bold: true
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
          wrapMode: Text.Wrap
          maximumLineCount: 2
          elide: Text.ElideRight
        }
      }
    }
  }
}
