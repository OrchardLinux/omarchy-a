import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Networking
import "Model.js" as Model

// Orchard: the connection state the bar's icon shows, apart from the panel,
// so the status cluster, the lock and the control center show the same thing.
// The panel binds its own properties of these names to it.
Item {
  id: root
  visible: false

  readonly property bool networkManagerAvailable: Networking.backend === NetworkBackendType.NetworkManager
  readonly property var networkDevices: Networking.devices ? Networking.devices.values : []
  readonly property var wifiDevice: findDevice(DeviceType.Wifi)
  readonly property var wiredDevice: findDevice(DeviceType.Wired)
  readonly property var wifiNetworkObjects: wifiDevice && wifiDevice.networks ? wifiDevice.networks.values : []
  readonly property var connectedWifiNetwork: findConnectedWifiNetwork()
  readonly property bool wifiEnabled: Networking.wifiEnabled
  readonly property string ssid: connectedWifiNetwork ? String(connectedWifiNetwork.name || "") : ""

  // Prefer a connected device: a machine can expose several NICs of the
  // same type (e.g. an idle onboard port alongside the active adapter),
  // and the first-enumerated one may be carrierless.
  function findDevice(type) {
    var devices = networkDevices || []
    var fallback = null
    for (var i = 0; i < devices.length; i++) {
      var device = devices[i]
      if (!device || device.type !== type) continue
      if (device.connected) return device
      if (!fallback) fallback = device
    }
    return fallback
  }

  function findConnectedWifiNetwork() {
    var networks = wifiNetworkObjects || []
    for (var i = 0; i < networks.length; i++) {
      if (networks[i] && networks[i].connected) return networks[i]
    }
    return null
  }

  // Derived from the native NetworkManager service so the icon reflects
  // connection changes without polling. Wired is preferred when both are up,
  // matching the default-route device.
  readonly property string kind: {
    if (wiredDevice && wiredDevice.connected) return "ethernet"
    if (connectedWifiNetwork) return "wifi"
    // NetworkManager can leave the active profile out of the device's
    // AvailableConnections, and Quickshell only builds known networks from
    // that list. An OWE transition-mode network does this between scans: the
    // in-use access point carries the hidden "_owetm_" SSID, so the profile
    // for the open SSID looks out of range even while it is connected. Trust
    // the device's own state then instead of flickering to disconnected.
    if (wifiDevice && wifiDevice.connected) return "wifi"
    return "disconnected"
  }
  readonly property int signalStrength: kind === "wifi"
    ? Model.connectedSignalStrength(connectedWifiNetwork ? connectedWifiNetwork.signalStrength : 0, activeApSignal)
    : -1
  // Filled by activeApSignalPoll from nmcli while the connected network has no
  // strength of its own to report.
  property int activeApSignal: -1
  readonly property bool needsActiveApSignal: kind === "wifi"
    && !(connectedWifiNetwork && connectedWifiNetwork.signalStrength > 0)
  // Bumped whenever the cached reading stops describing the current link, so
  // an nmcli read still in flight from before cannot write a stale strength.
  property int activeApSignalGeneration: 0
  property int activeApSignalRequest: -1
  onKindChanged: if (kind !== "wifi") resetActiveApSignal()
  onWifiDeviceChanged: resetActiveApSignal()

  // Switching Wi-Fi networks always passes through a non-"wifi" kind (both the
  // device and the old network drop out of the connected state while the new
  // profile activates), so this also covers a change of network.
  function resetActiveApSignal() {
    activeApSignal = -1
    activeApSignalGeneration++
  }

  function pollActiveApSignal() {
    if (activeApSignalProc.running) return
    activeApSignalRequest = activeApSignalGeneration
    activeApSignalProc.running = true
  }

  function finishActiveApSignal(raw) {
    if (activeApSignalRequest !== activeApSignalGeneration) {
      // The link changed mid-read and the restarted poll skipped while this
      // one was running; read again now instead of a full interval later.
      if (needsActiveApSignal) activeApSignalPoll.restart()
      return
    }
    activeApSignal = Model.parseActiveApSignal(raw)
  }

  // NetworkManager performs the HTTP probe (including unexpected page bodies,
  // not just redirects). Consume its native notifications rather than running
  // a second curl loop or mistaking an ordinary timeout for a captive portal.
  readonly property bool connectivityChecksEnabled: networkManagerAvailable
    && Networking.canCheckConnectivity && Networking.connectivityCheckEnabled
  readonly property string connectivity: Model.connectivityState(kind, Networking.connectivity, {
    Portal: NetworkConnectivity.Portal, Limited: NetworkConnectivity.Limited,
    Full: NetworkConnectivity.Full, None: NetworkConnectivity.None
  }, connectivityChecksEnabled, limitedSettled)
  // A network switch passes through Limited for a fraction of a second while
  // NetworkManager's first probe is in flight. Wait that out rather than flash
  // the outage warning on every connect.
  readonly property bool nativeLimited: Networking.connectivity === NetworkConnectivity.Limited
  property bool limitedSettled: false
  onNativeLimitedChanged: if (!nativeLimited) limitedSettled = false
  Timer {
    interval: 3000
    running: root.nativeLimited
    onTriggered: root.limitedSettled = true
  }
  readonly property bool hasCaptivePortal: connectivity === "portal"
  readonly property bool restricted: hasCaptivePortal || connectivity === "limited"
  readonly property string icon: Model.connectionIcon(kind, signalStrength, connectivity)

  // Reads the in-use access point's strength without triggering a scan, for
  // the connected network that has none of its own (see signalStrength).
  Process {
    id: activeApSignalProc
    command: ["nmcli", "-t", "-f", "IN-USE,SIGNAL", "device", "wifi", "list", "ifname", root.wifiDevice ? root.wifiDevice.name : "", "--rescan", "no"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.finishActiveApSignal(text)
    }
  }

  Timer {
    id: activeApSignalPoll
    interval: 5000
    repeat: true
    triggeredOnStart: true
    running: root.needsActiveApSignal
    onTriggered: root.pollActiveApSignal()
  }
}
