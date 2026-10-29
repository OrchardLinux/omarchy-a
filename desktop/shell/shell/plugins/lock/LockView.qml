import QtQuick
import QtQuick.Effects
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

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
  // A locked session blanks the displays after a few seconds. Nothing is
  // visible from then until the user wakes it, so a video must not keep
  // decoding through what is usually the longest part of a lock.
  property bool displaysBlank: false
  property bool powerSaverActive: false
  property string passwordText: ""
  property bool syncingPasswordText: false

  readonly property bool touchPin: Quickshell.env("OMARCHY_TOUCH_MODE") === "1"
  readonly property string placeholderText: touchPin ? "Enter PIN" : Commons.I18n.t("lock.enterPassword")
  readonly property int fieldWidth: Math.min(touchPin ? 465 : 381, Math.max(1, width - 48))
  readonly property int fieldHeight: touchPin ? 93 : 67
  readonly property int outlineThickness: 3
  readonly property int fieldFontSize: Math.round(Style.font.heading * 1.125)
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

  readonly property bool video: Util.isVideoPath(root.backgroundPath)
  readonly property bool feedActive: root.video && root.loadBackground && !root.displaysBlank && !root.powerSaverActive

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

  onPasswordTextChanged: syncPasswordText()
  onInputEnabledChanged: {
    if (inputEnabled) Qt.callLater(forcePasswordFocus)
  }
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

    MultiEffect {
      anchors.fill: wallpaper
      source: wallpaper
      autoPaddingEnabled: false
      blurEnabled: root.loadBackground && wallpaper.ready
      blur: 1.0
      blurMax: 128
      blurMultiplier: 1.25
      contrast: -0.08
    }

    // The cached poster stays behind the feed when policy pauses playback,
    // the module is unavailable, or a new connection has not received a frame.
    Loader {
      id: feedLoader
      objectName: "lockFeedLoader"
      anchors.fill: parent
      active: root.feedActive
      source: "LockFeedSurface.qml"
      visible: status === Loader.Ready
    }

    // The feed item cannot be sampled by MultiEffect on every renderer.
    // Keep video wallpapers visible and darken them slightly for legibility.
    Rectangle {
      anchors.fill: feedLoader
      visible: root.video
      color: "#22000000"
    }

    MouseArea {
      anchors.fill: parent
      // Creating a lock surface can synthesize a pointer movement. On a tablet
      // that is not a wake gesture and must not undo Power's immediate blank.
      hoverEnabled: !root.touchPin
      onClicked: { root.wakeRequested(); root.forcePasswordFocus() }
      onPositionChanged: if (!root.touchPin) root.wakeRequested()
    }

    BorderSurface {
      id: inputField
      width: root.fieldWidth
      height: root.fieldHeight
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.verticalCenter: parent.verticalCenter
      anchors.verticalCenterOffset: root.touchPin ? -Math.min(170, Math.round(root.height * 0.17)) : 0
      color: root.touchPin ? "transparent" : Commons.Color.lock.background
      borderSpec: root.touchPin ? Border.none() : root.inputBorderSpec
      radius: Style.cornerRadius
      clip: true

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
        opacity: root.touchPin ? 0 : 1
        maximumLength: root.touchPin ? 6 : 32767
        inputMethodHints: root.touchPin ? Qt.ImhDigitsOnly | Qt.ImhNoPredictiveText | Qt.ImhSensitiveData : Qt.ImhSensitiveData
        echoMode: TextInput.Password
        passwordCharacter: "\u25CF"
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
          color: Commons.Color.lock.text
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
          root.wakeRequested()
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
        text: root.authenticatingPassword ? Commons.I18n.t("lock.checking") : (root.failureMessage.length > 0 ? root.failureMessage : root.placeholderText)
        visible: !root.touchPin && passwordInput.text.length === 0
        color: root.authenticatingPassword ? Commons.Color.lock.text : (root.failureMessage.length > 0 ? Commons.Color.lock.textError : Commons.Color.lock.placeholder)
        font.family: Style.font.family
        font.pixelSize: root.fieldFontSize
        font.italic: !root.authenticatingPassword && root.failureMessage.length > 0
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

    Column {
      anchors.centerIn: inputField
      spacing: 26
      visible: root.touchPin

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.authenticatingPassword ? Commons.I18n.t("lock.checking") : (root.errorState ? root.failureMessage : root.placeholderText)
        color: root.errorState ? Commons.Color.lock.textError : Commons.Color.lock.text
        font.family: Style.font.family
        font.pixelSize: Math.max(26, root.fieldFontSize)
        horizontalAlignment: Text.AlignHCenter
        width: root.fieldWidth
        elide: Text.ElideRight
      }
      Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 26
        Repeater {
          model: 6
          Rectangle {
            required property int index
            width: 18; height: 18; radius: 9
            // The PIN itself is cleared on submit; keep only its visual
            // indicator filled until authentication finishes.
            color: root.authenticatingPassword || index < root.passwordText.length ? Commons.Color.lock.text : "transparent"
            border.width: 2
            border.color: root.errorState ? Commons.Color.lock.textError : Commons.Color.lock.text
          }
        }
      }
    }

    Grid {
      anchors.top: inputField.bottom
      anchors.topMargin: 60
      anchors.horizontalCenter: parent.horizontalCenter
      visible: root.touchPin
      columns: 3
      rowSpacing: 12
      columnSpacing: 12
      Repeater {
        model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"]
        BorderSurface {
          id: pinKey
          required property string modelData
          readonly property bool backspaceKey: modelData === "⌫"
          width: (root.fieldWidth - 24) / 3
          height: 70
          radius: Style.cornerRadius
          color: backspaceKey ? "transparent" : Commons.Color.lock.background
          borderSpec: backspaceKey ? Border.none() : Border.surfaceSpec("lock", "border", Commons.Color.lock.border, 1, "border-alpha")
          opacity: modelData === "" ? 0 : (root.inputEnabled && !root.authenticatingPassword ? 1 : 0.55)

          Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: Math.max(0, Style.cornerRadius - 1)
            color: pinMouse.pressed
              ? Style.pressedFillFor(Commons.Color.lock.text, Commons.Color.accent)
              : (pinKey.backspaceKey ? "transparent" : Style.normalFillFor(Commons.Color.lock.text, Commons.Color.accent))
          }
          Text {
            anchors.centerIn: parent
            text: pinKey.modelData
            color: pinKey.backspaceKey ? Commons.Color.lock.placeholder : Commons.Color.lock.text
            font.family: Style.font.family
            font.pixelSize: Math.max(27, Math.round(Style.font.heading * 1.1))
          }
          MouseArea {
            id: pinMouse
            anchors.fill: parent
            enabled: pinKey.modelData !== "" && root.inputEnabled && !root.authenticatingPassword
            onClicked: {
              root.wakeRequested()
              if (pinKey.modelData === "⌫") root.editPin(root.passwordText.slice(0, -1))
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

    // The crossed-out icon has no meaning to a user who has never seen it — it
    // is not intuitive that it signals a broken reader — so the words carry the
    // explanation and the icon only reinforces it.
    Text {
      objectName: "fingerprintUnavailableNotice"
      textFormat: Text.PlainText
      anchors.top: inputField.bottom
      anchors.topMargin: 18
      anchors.horizontalCenter: inputField.horizontalCenter
      visible: !root.touchPin && root.fingerprintConfigured && root.fingerprintUnavailable
      text: Commons.I18n.t("lock.fingerprintUnavailable")
      color: Commons.Color.lock.textError
      font.family: Style.font.family
      font.pixelSize: Style.font.heading
      font.italic: true
      horizontalAlignment: Text.AlignHCenter
    }
  }
}
