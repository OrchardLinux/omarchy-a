import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Bluetooth
import qs.Commons
import qs.Commons as Commons
import "../plugins/panels/bluetooth/Model.js" as BluetoothModel

// Bluetooth: the switch, my devices (a tap connects or disconnects), and the
// devices nearby while the page shows (a tap pairs), through the commands the
// control center uses. The lists hold plain rows (an address and a name),
// never BlueZ's device objects, which go away at any moment.
Item {
  id: page

  property var settings: null

  width: parent ? parent.width : 0
  height: column.height

  readonly property var adapter: Bluetooth.defaultAdapter
  readonly property bool powered: !!adapter && adapter.enabled
  readonly property var devices: Bluetooth.devices ? Bluetooth.devices.values : []
  readonly property var groups: BluetoothModel.deviceLists(devices)

  // Searching while the page shows; the host ends it after (Settings.qml).
  Component.onCompleted: if (settings && settings.host) settings.host.bluetoothScan = true
  Component.onDestruction: if (settings && settings.host) settings.host.bluetoothScan = false

  function rowsOf(list) {
    var out = []
    for (var i = 0; i < list.length; i++) {
      var d = list[i]
      if (!d) continue
      out.push({ address: String(d.address), label: BluetoothModel.deviceLabel(d),
                 connected: !!d.connected, bonded: !!d.bonded, icon: String(d.icon || "") })
    }
    return out
  }
  readonly property var mine: rowsOf(groups.connected.concat(groups.known))
  readonly property var nearby: rowsOf(groups.discovered)

  // One action at a time, as in the control center: the address it is for and
  // what it does.
  property string busyAddress: ""
  property string busyAction: ""
  function act(row) {
    if (actionProc.running) return
    var action = row.connected ? "disconnect" : (row.bonded ? "connect" : "pair")
    page.busyAddress = row.address
    page.busyAction = action
    actionProc.command = ["omarchy-bluetooth-device", action, row.address]
    actionProc.running = true
  }
  Process {
    id: actionProc
    onExited: { page.busyAddress = ""; page.busyAction = "" }
  }

  function stateOf(row) {
    if (row.address === page.busyAddress) {
      return page.busyAction === "disconnect" ? Commons.I18n.t("bluetooth.disconnecting") : Commons.I18n.t("bluetooth.connecting")
    }
    return row.connected ? Commons.I18n.t("settings.connected") : (row.bonded ? Commons.I18n.t("settings.notConnected") : "")
  }

  function glyphFor(icon) {
    if (icon.indexOf("audio") >= 0 || icon.indexOf("headset") >= 0 || icon.indexOf("headphone") >= 0) return "󰋋"
    if (icon.indexOf("keyboard") >= 0) return "󰌌"
    if (icon.indexOf("mouse") >= 0) return "󰍽"
    if (icon.indexOf("phone") >= 0) return "󰍲"
    return "󰂯"
  }

  Column {
    id: column
    width: page.width
    spacing: Style.space(14)

    SettingsBox {
      settings: page.settings
      width: parent.width
      SettingsItem {
        settings: page.settings
        first: true
        label: Commons.I18n.t("settings.bluetooth")
        isSwitch: true
        switchOn: page.powered
        usable: !!page.adapter
        // As the control center switches it: the choice outlives a reboot.
        onActivated: Quickshell.execDetached(["omarchy-bluetooth-power", page.powered ? "off" : "on"])
      }
    }

    SettingsBox {
      settings: page.settings
      width: parent.width
      title: Commons.I18n.t("settings.myDevices")
      visible: page.powered && page.mine.length > 0
      Repeater {
        model: page.mine
        SettingsItem {
          required property var modelData
          required property int index
          settings: page.settings
          first: index === 0
          glyph: page.glyphFor(modelData.icon)
          accent: modelData.connected
          label: modelData.label
          value: page.stateOf(modelData)
          onActivated: page.act(modelData)
        }
      }
    }

    SettingsBox {
      settings: page.settings
      width: parent.width
      title: Commons.I18n.t("settings.otherDevices")
      visible: page.powered
      SettingsItem {
        visible: page.nearby.length === 0
        settings: page.settings
        first: true
        label: Commons.I18n.t("settings.searching")
        usable: false
      }
      Repeater {
        model: page.nearby
        SettingsItem {
          required property var modelData
          required property int index
          settings: page.settings
          first: index === 0
          glyph: page.glyphFor(modelData.icon)
          label: modelData.label
          value: page.stateOf(modelData)
          onActivated: page.act(modelData)
        }
      }
    }
  }
}
