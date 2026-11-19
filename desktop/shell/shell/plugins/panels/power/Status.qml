import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower
import "Model.js" as Model

// Orchard: the battery state the bar's icon shows, apart from the panel, so
// the status cluster, the lock and the control center show the same thing.
// The panel binds its own properties of these names to it.
Item {
  id: root
  visible: false

  // The battery script's readings (omarchy-battery-status --shell), read
  // every second: discovery must not depend on a charger event or on UPower.
  property var batteryInfo: ({})
  readonly property bool externalPower: batteryInfo.external_power === "connected"
  readonly property var batteryDevice: {
    var device = UPower.displayDevice
    if (device && device.isPresent) return device
    var measured = Model.batteryPercentage(null, root.batteryInfo)
    // Do not invent a charging/discharging state when only capacity is known.
    return measured === null ? null : { isPresent: true, percentage: measured / 100, state: 0 }
  }
  readonly property bool batteryPresent: batteryDevice !== null
  readonly property var displayedPercentage: Model.batteryPercentage(batteryDevice, batteryInfo)
  readonly property bool discharging: {
    var device = UPower.displayDevice
    return !!(device && device.isPresent && device.state === UPowerDeviceState.Discharging)
  }
  readonly property string icon: Model.batteryIcon(batteryDevice, discharging, upowerStates(), externalPower)

  function upowerStates() {
    return {
      Charging: UPowerDeviceState.Charging,
      Discharging: UPowerDeviceState.Discharging,
      FullyCharged: UPowerDeviceState.FullyCharged,
      PendingCharge: UPowerDeviceState.PendingCharge
    }
  }

  function refresh() {
    if (!batteryProc.running) batteryProc.running = true
  }

  function updateKeyValue(raw) {
    var next = Model.parseKeyValue(raw)
    // Keep last known good data if a refresh briefly returns nothing — happens
    // around AC plug/unplug events. Avoids the section collapsing mid-transition.
    if (Object.keys(next).length > 0) batteryInfo = next
    else batteryInfo = Object.assign({}, batteryInfo, { external_power: "unknown" })
  }

  Process {
    id: batteryProc
    command: ["omarchy-battery-status", "--shell"]
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.updateKeyValue(text) }
  }

  Timer {
    interval: 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }
}
