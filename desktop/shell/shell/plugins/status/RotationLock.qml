import QtQuick
import Quickshell
import Quickshell.Io

// Whether rotation is locked: omarchy-rotation-lock's file, which only exists
// while it is. Read every two seconds, as a missing file cannot be watched.
// And whether there is anything to lock: iio-sensor-proxy's accelerometer,
// which the rotation daemon follows. Without one the lock is unavailable.
Item {
  id: root
  visible: false
  property bool locked: false
  // Until the proxy has answered, assume a sensor: nothing greys out at start.
  property bool sensor: true

  Process {
    id: probe
    command: ["busctl", "get-property", "net.hadess.SensorProxy", "/net/hadess/SensorProxy",
      "net.hadess.SensorProxy", "HasAccelerometer"]
    stdout: StdioCollector { id: probeOut }
    onExited: function(exitCode) {
      root.sensor = exitCode === 0 && probeOut.text.trim() === "b true"
    }
  }
  Component.onCompleted: probe.running = true
  // The proxy may still be starting when the shell does: ask once more.
  Timer {
    interval: 10000
    running: true
    onTriggered: if (!root.sensor) probe.running = true
  }

  FileView {
    id: file
    path: (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")) + "/omarchy/rotation-lock"
    printErrors: false
    onLoaded: root.locked = true
    onLoadFailed: root.locked = false
  }
  Timer {
    interval: 2000
    running: true
    repeat: true
    onTriggered: file.reload()
  }
}
