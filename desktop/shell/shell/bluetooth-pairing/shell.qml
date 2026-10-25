import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Separate process from the extensible main shell: authentication input and
// pending replies are never placed on a bar widget or a shared plugin service.
ShellRoot {
  id: root
  property color backgroundColor: "#121212"
  property color foregroundColor: "#eeeeee"
  property color accentColor: "#a0c980"
  property string deviceName: "Bluetooth accessory"
  property string status: "Preparing secure pairing…"
  property var prompt: null
  property string displayCode: ""
  property bool failed: false
  property bool cancelling: false
  property bool complete: false
  property bool finished: false
  readonly property bool needsInput: prompt !== null && (prompt.kind === "pin" || prompt.kind === "passkey")
  readonly property bool touchMode: Quickshell.env("OMARCHY_TOUCH_MODE") === "1"
  Component.onCompleted: Quickshell.watchFiles = false

  function cancel() {
    if (finished) { Qt.quit(); return }
    if (cancelling) return
    cancelling = true
    status = "Cancelling…"
    backend.write(JSON.stringify({action: "cancel"}) + "\n")
    cancelDeadline.start()
  }

  function respond(accept) {
    if (!prompt || cancelling) return
    backend.write(JSON.stringify({action: "reply", id: prompt.id, accept: accept, value: input.text}) + "\n")
    if (accept) status = "Waiting for the accessory…"
  }

  function handleLine(line) {
    var message
    try { message = JSON.parse(line) } catch (_) { cancel(); return }
    switch (message.event) {
    case "theme":
      backgroundColor = message.background
      foregroundColor = message.foreground
      accentColor = message.accent
      break
    case "device": deviceName = String(message.name || deviceName); break
    case "progress": status = message.message; displayCode = ""; break
    case "prompt":
      prompt = message
      displayCode = String(message.code || "")
      input.text = ""
      status = message.kind === "repair"
        ? "Replace the incomplete pairing saved on this iPad? Then switch the accessory off and on again."
        : message.kind === "confirm"
          ? "Compare this code if your accessory has a display. Only approve the accessory you intended to pair."
          : message.kind === "authorize" ? "Allow pairing/service access for this accessory?"
          : message.kind === "passkey" ? "Enter the six-digit passkey supplied by the accessory."
          : "Enter the PIN supplied by the accessory."
      Qt.callLater(function() { if (root.needsInput) input.forceActiveFocus(); else cancelButton.forceActiveFocus() })
      break
    case "display":
      prompt = null
      displayCode = String(message.code || "")
      status = "Type this code on the accessory, then press Return."
      break
    case "validation_error": status = message.message; break
    case "clear": prompt = null; input.text = ""; displayCode = ""; break
    case "error": failed = true; status = message.message; break
    case "cancelled": cancelling = true; break
    case "complete": complete = true; break
    }
  }

  Process {
    id: backend
    command: ["/usr/libexec/omarchy-bluetooth-pair", String(Quickshell.env("OMARCHY_PAIR_ADDRESS") || "")]
    stdinEnabled: true
    running: true
    stdout: SplitParser { onRead: function(line) { root.handleLine(line) } }
    // No raw D-Bus output, device identifiers or pairing codes in shell logs.
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(exitCode) {
      root.finished = true
      root.prompt = null
      input.text = ""
      cancelDeadline.stop()
      if (exitCode === 0 && root.complete) Qt.quit()
      else if (root.cancelling) Qt.quit()
      else { root.failed = true; if (root.status === "Preparing secure pairing…") root.status = "Unable to start pairing." }
    }
  }

  Timer { id: cancelDeadline; interval: 5000; onTriggered: { backend.running = false; Qt.quit() } }

  component Choice: Controls.Button {
    id: choice
    font.family: "monospace"
    font.pixelSize: 14
    implicitHeight: 44
    padding: 12
    Keys.onReleased: function(event) {
      if (enabled && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
        clicked()
        event.accepted = true
      }
    }
    contentItem: Text {
      text: choice.text
      textFormat: Text.PlainText
      color: root.foregroundColor
      opacity: choice.enabled ? 1 : 0.45
      font: choice.font
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
      color: choice.down ? root.accentColor : root.backgroundColor
      border.color: choice.activeFocus || choice.hovered ? root.accentColor : root.foregroundColor
      border.width: choice.activeFocus ? 2 : 1
      opacity: choice.enabled ? 1 : 0.45
    }
  }

  PanelWindow {
    id: overlay
    screen: Quickshell.screens.length > 0 ? Quickshell.screens[0] : null
    visible: true
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: root.touchMode ? WlrLayer.Top : WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    Rectangle { anchors.fill: parent; color: root.backgroundColor; opacity: 0.78 }
    FocusScope {
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: function(event) { root.cancel(); event.accepted = true }

      Rectangle {
        id: card
        width: Math.min(parent.width - 32, 460)
        height: column.implicitHeight + 48
        anchors.horizontalCenter: parent.horizontalCenter
        // Leave space for the touch keyboard while a PIN field is present.
        y: Math.max(16, (parent.height - height - (root.touchMode && root.needsInput ? 270 : 0)) / 2)
        color: root.backgroundColor
        border.color: root.accentColor
        border.width: 1
        Column {
          id: column
          anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 }
          spacing: 16
          Text {
            width: parent.width; text: "BLUETOOTH PAIRING"; textFormat: Text.PlainText
            color: root.accentColor; font.family: "monospace"; font.pixelSize: 14
          }
          Text {
            width: parent.width; text: root.deviceName; textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: root.foregroundColor; font.family: "monospace"; font.pixelSize: 20
          }
          Text {
            width: parent.width; text: String(Quickshell.env("OMARCHY_PAIR_ADDRESS") || ""); textFormat: Text.PlainText
            color: root.foregroundColor; opacity: 0.6; font.family: "monospace"; font.pixelSize: 12
          }
          Text {
            width: parent.width; text: root.status; textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: root.foregroundColor; font.family: "monospace"; font.pixelSize: 14
          }
          Text {
            width: parent.width; visible: root.prompt !== null && !!root.prompt.service
            text: root.prompt && root.prompt.service ? "Service: " + String(root.prompt.service) : ""
            textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: root.foregroundColor; font.family: "monospace"; font.pixelSize: 12
          }
          Text {
            width: parent.width; visible: text !== ""; text: root.displayCode; textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            color: root.accentColor; font.family: "monospace"; font.pixelSize: 36; font.letterSpacing: 5
          }
          Controls.TextField {
            id: input
            width: parent.width; visible: root.needsInput; enabled: !root.cancelling
            maximumLength: root.prompt && root.prompt.kind === "passkey" ? 6 : 16
            color: root.foregroundColor; font.family: "monospace"; font.pixelSize: 14
            implicitHeight: 44; padding: 12; selectByMouse: true
            placeholderTextColor: Qt.rgba(root.foregroundColor.r, root.foregroundColor.g, root.foregroundColor.b, 0.55)
            inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhSensitiveData
            placeholderText: root.prompt && root.prompt.kind === "passkey" ? "Passkey" : "PIN"
            onAccepted: root.respond(true)
            background: Rectangle { color: Qt.rgba(root.foregroundColor.r, root.foregroundColor.g, root.foregroundColor.b, 0.05); border.color: input.activeFocus ? root.accentColor : root.foregroundColor }
          }
          Row {
            spacing: 12
            Choice {
              id: cancelButton
              text: root.finished ? "Close" : "Cancel"
              enabled: !root.cancelling || root.finished
              onClicked: root.cancel()
            }
            Choice {
              visible: root.prompt !== null
              enabled: !root.cancelling && (!root.needsInput || input.text.length > 0)
              text: root.needsInput ? "Submit" : root.prompt && root.prompt.kind === "repair" ? "Replace pairing" : "Approve"
              onClicked: root.respond(true)
            }
            Choice {
              visible: root.touchMode && root.needsInput
              text: "Keyboard"
              onClicked: { input.forceActiveFocus(); Quickshell.execDetached(["omarchy-keyboard", "toggle"]) }
            }
          }
        }
      }
    }
  }
}
