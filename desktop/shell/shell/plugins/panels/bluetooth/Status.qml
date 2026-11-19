import QtQuick
import Quickshell
import Quickshell.Bluetooth
import "Model.js" as Model

// Orchard: the Bluetooth state the bar's icon shows, apart from the panel, so
// the status cluster, the lock and the control center show the same thing.
Item {
  id: root
  visible: false

  readonly property var adapter: Bluetooth.defaultAdapter
  readonly property bool enabled: !!(adapter && adapter.enabled)
  readonly property var devices: Bluetooth.devices ? Bluetooth.devices.values : []
  readonly property var connectedDevices: (Model.deviceLists(devices).connected) || []
  readonly property string icon: {
    if (!adapter) return ""
    if (!adapter.enabled) return "󰂲"
    if (connectedDevices.length > 0) return "󰂱"
    return "󰂯"
  }
}
