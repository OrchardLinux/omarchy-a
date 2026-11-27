import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Networking
import qs.Commons
import qs.Commons as Commons
import "../plugins/panels/network" as Network
import "../plugins/panels/network/Model.js" as NetModel

// One network's page (Wi-Fi > a known network's info button, or the network
// in use): join or disconnect, forget, auto-join, and while connected its
// addresses. The network is looked up by name each time, never held: a scan
// can delete the object (WifiPage says why).
Item {
  id: page

  property var settings: null
  readonly property string ssid: settings && settings.top && settings.top.ssid ? settings.top.ssid : ""

  width: parent ? parent.width : 0
  height: column.height

  Network.Status { id: status }

  readonly property var network: {
    var list = status.wifiNetworkObjects || []
    for (var i = 0; i < list.length; i++) if (list[i] && list[i].name === page.ssid) return list[i]
    return null
  }
  readonly property bool connected: !!network && network.connected
  readonly property bool known: !!network && network.known
  readonly property bool changing: !!network && network.stateChanging
  Process { id: cancelProc }
  readonly property string device: status.wifiDevice ? String(status.wifiDevice.name || "") : ""

  // What NetworkManager has on it: its saved profile (auto-join, security)
  // and, while connected, the device's addresses.
  property string uuid: ""
  property bool autoJoin: true
  property string keyMgmt: ""
  property string address: ""
  property string router: ""
  property var dns: []
  property bool ready: false
  function read() { if (!reader.running) reader.running = true }
  Component.onCompleted: read()
  onConnectedChanged: read()
  onKnownChanged: { read(); if (!known && !changing && ready && settings) settings.back() }
  Process {
    id: reader
    command: ["bash", "-c", [
      "ssid=$1 dev=$2",
      "while IFS=: read -r u t; do",
      "  [[ $t == 802-11-wireless ]] || continue",
      "  [[ $(nmcli -g 802-11-wireless.ssid connection show \"$u\" 2>/dev/null) == \"$ssid\" ]] || continue",
      "  printf 'uuid\\t%s\\n' \"$u\"",
      "  printf 'auto\\t%s\\n' \"$(nmcli -g connection.autoconnect connection show \"$u\")\"",
      "  printf 'key\\t%s\\n' \"$(nmcli -g 802-11-wireless-security.key-mgmt connection show \"$u\")\"",
      "  break",
      "done < <(nmcli -g UUID,TYPE connection show 2>/dev/null)",
      "[[ -n $dev ]] && nmcli -t -f IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show \"$dev\" 2>/dev/null | sed 's/^/ip\\t/'"
    ].join("\n"), "wifi-network", page.ssid, page.connected ? page.device : ""]
    stdout: StdioCollector {
      onStreamFinished: {
        var uuid = "", auto = true, key = "", address = "", router = "", dns = []
        var lines = String(text).split("\n")
        for (var i = 0; i < lines.length; i++) {
          var parts = lines[i].split("\t")
          if (parts[0] === "uuid") uuid = parts[1] || ""
          else if (parts[0] === "auto") auto = parts[1] !== "no"
          else if (parts[0] === "key") key = parts[1] || ""
          else if (parts[0] === "ip") {
            var at = (parts[1] || "").indexOf(":")
            if (at < 0) continue
            var name = parts[1].slice(0, at), value = parts[1].slice(at + 1)
            if (value === "" || value === "--") continue
            if (name.indexOf("IP4.ADDRESS") === 0 && address === "") address = value.replace(/\/\d+$/, "")
            else if (name === "IP4.GATEWAY") router = value
            else if (name.indexOf("IP4.DNS") === 0) dns.push(value)
          }
        }
        page.uuid = uuid
        page.autoJoin = auto
        page.keyMgmt = key
        page.address = page.connected ? address : ""
        page.router = page.connected ? router : ""
        page.dns = page.connected ? dns : []
        page.ready = true
      }
    }
  }
  Process {
    id: writer
    onExited: page.read()
  }
  function setAutoJoin(on) {
    if (page.uuid === "") return
    page.autoJoin = on
    writer.command = ["nmcli", "connection", "modify", "uuid", page.uuid, "connection.autoconnect", on ? "yes" : "no"]
    writer.running = true
  }

  readonly property string securityName: {
    if (page.keyMgmt === "sae") return "WPA3"
    if (page.keyMgmt === "wpa-psk") return "WPA2"
    if (page.keyMgmt === "wpa-eap" || page.keyMgmt === "wpa-eap-suite-b-192") return Commons.I18n.t("settings.wifiEnterprise")
    if (page.keyMgmt === "owe") return "OWE"
    if (page.keyMgmt === "none") return "WEP"
    return page.known && page.uuid !== "" ? Commons.I18n.t("settings.wifiOpen") : ""
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
        accent: true
        label: page.connected ? Commons.I18n.t("settings.wifiDisconnect") : Commons.I18n.t("settings.wifiJoin")
        value: page.changing ? (page.connected ? Commons.I18n.t("network.disconnecting") : Commons.I18n.t("network.connecting")) : ""
        usable: !!page.network && !page.changing
        onActivated: {
          if (!page.network) return
          if (page.connected) page.network.disconnect()
          // A tap while it connects stops it (NetModel.cancelConnectScript).
          else if (page.changing) { cancelProc.command = ["bash", "-c", NetModel.cancelConnectScript, "nmcli-cancel", page.device]; cancelProc.running = true }
          else page.network.connect()
        }
      }
      SettingsItem {
        visible: page.known
        settings: page.settings
        accent: true
        label: Commons.I18n.t("settings.wifiForget")
        usable: !page.changing
        onActivated: if (page.network) page.network.forget()
      }
    }

    SettingsBox {
      visible: page.known && page.uuid !== ""
      settings: page.settings
      width: parent.width
      SettingsItem {
        settings: page.settings
        first: true
        label: Commons.I18n.t("settings.wifiAutoJoin")
        isSwitch: true
        switchOn: page.autoJoin
        onActivated: page.setAutoJoin(!page.autoJoin)
      }
    }

    SettingsBox {
      settings: page.settings
      width: parent.width
      title: Commons.I18n.t("settings.wifiDetails")
      SettingsItem {
        settings: page.settings
        first: true
        label: Commons.I18n.t("settings.wifiSignal")
        value: page.network ? Math.round((page.network.signalStrength || 0) * 100) + "%" : ""
      }
      SettingsItem {
        visible: page.securityName !== ""
        settings: page.settings
        label: Commons.I18n.t("settings.wifiSecurity")
        value: page.securityName
      }
      SettingsItem {
        visible: page.address !== ""
        settings: page.settings
        label: Commons.I18n.t("network.ipAddress")
        value: page.address
      }
      SettingsItem {
        visible: page.router !== ""
        settings: page.settings
        label: Commons.I18n.t("settings.wifiRouter")
        value: page.router
      }
      SettingsItem {
        visible: page.dns.length > 0
        settings: page.settings
        label: Commons.I18n.t("settings.wifiDns")
        value: page.dns.join(", ")
      }
    }
  }
}
