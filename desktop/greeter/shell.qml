import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Services.Greetd
import "plugins/lock" as Lock

ShellRoot {
    id: root
    property string pin: ""
    property string submittedPin: ""
    property bool busy: false
    property string failure: ""
    readonly property string themeDir: Quickshell.env("OMARCHY_GREETER_THEME_DIR")

    function submit(value) {
        if (busy || !/^[0-9]{6}$/.test(value)) return
        if (!Greetd.available) { failure = "Authentication is unavailable"; return }
        failure = ""
        submittedPin = value
        busy = true
        Greetd.createSession("tablet")
    }
    Connections {
        target: Greetd
        function onAuthMessage(message, error, responseRequired, echoResponse) {
            if (responseRequired && !echoResponse && root.submittedPin !== "") {
                const answer = root.submittedPin
                root.submittedPin = ""
                Greetd.respond(answer)
            } else if (responseRequired) {
                root.submittedPin = ""
                root.busy = false
                root.failure = "Unsupported authentication prompt"
                Greetd.cancelSession()
            } else if (error) {
                root.failure = "Authentication failed. Try again."
            }
        }
        function onAuthFailure(message) {
            root.submittedPin = ""
            root.pin = ""
            root.busy = false
            root.failure = "PIN not accepted. Try again."
        }
        function onError(error) {
            root.submittedPin = ""
            root.pin = ""
            root.busy = false
            root.failure = "PIN not accepted, or sign-in temporarily unavailable."
        }
        function onReadyToLaunch() {
            root.submittedPin = ""
            Greetd.launch(["/usr/local/libexec/arch-ipad-login-session"])
        }
    }

    // The PIN screen is on: record it for the installer (omarchy-desktop-ready)
    Process {
        id: readiness
        command: ["/usr/libexec/omarchy-desktop-ready"]
    }
    Component.onCompleted: Qt.callLater(function() { readiness.running = true })

    // No input for 30 s: dark, then sleep, through omarchy-powerd like everything
    // else. Repeated while idle: it does nothing once dark, and a wake that does
    // not count as input here cannot leave the panel lit for good.
    IdleMonitor {
        id: idle
        timeout: 30
        respectInhibitors: false
    }
    Process {
        id: darken
        command: ["/usr/libexec/omarchy-powerctl", "idle"]
    }
    Timer {
        interval: 30000
        repeat: true
        running: idle.isIdle
        triggeredOnStart: true
        onTriggered: darken.running = true
    }

    PanelWindow {
        id: window
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"
        WlrLayershell.namespace: "orchard-greeter"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

        // Labwc holds the previous session's last picture until this file
        // exists (handoverDirectory): the pad appears with its wallpaper drawn.
        property int drawnFrames: 0
        FrameAnimation {
            running: view.backgroundDrawn && window.drawnFrames < 3
            onTriggered: {
                window.drawnFrames += 1
                var file = Quickshell.env("LABWC_STARTUP_READY") || ""
                if (window.drawnFrames === 3 && file !== "") Quickshell.execDetached(["touch", file])
            }
        }
        Lock.LockView {
            id: view
            anchors.fill: parent
            backgroundPath: root.themeDir + "/background"
            passwordText: root.pin
            authenticatingPassword: root.busy
            failureMessage: root.failure
            inputEnabled: true
            onPasswordTextEdited: function(value) { root.pin = value }
            onSubmitPassword: function(value) { root.submit(value) }
            onClearFailureRequested: root.failure = ""
        }
    }
}
