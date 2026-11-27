import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Networking
import qs.Commons
import qs.Commons as Commons
import "../plugins/panels/network" as Network
import "../plugins/panels/network/Model.js" as NetModel

// Wi-Fi: the switch, the network in use, known and other networks (a tap
// joins; a network that needs a password asks for it in place; a known
// network's info button opens its page, WifiNetworkPage), through the
// same NetworkManager calls as the control center's network page. The list
// holds plain rows, never the networks themselves, which a scan can delete
// while a row is being built (the control center's Model.wifiRow says why).
Item {
  id: page

  property var settings: null

  width: parent ? parent.width : 0
  height: column.height

  Network.Status { id: status }

  readonly property bool wifiOn: status.wifiEnabled
  readonly property bool hasWifi: !!status.wifiDevice

  // Scanning while the page shows.
  property var scanner: null
  function scan(on) {
    var device = on ? status.wifiDevice : null
    if (page.scanner && page.scanner !== device) page.scanner.scannerEnabled = false
    page.scanner = device
    if (device) device.scannerEnabled = on
  }
  Component.onCompleted: scan(true)
  Component.onDestruction: scan(false)
  Connections {
    target: status
    function onWifiDeviceChanged() { page.scan(true) }
  }

  readonly property var rows: {
    var nets = []
    var list = status.wifiNetworkObjects || []
    for (var i = 0; i < list.length; i++) {
      var row = NetModel.wifiRow(list[i])
      if (!row || !row.ssid) continue
      row.changing = !!list[i].stateChanging
      nets.push(row)
    }
    return NetModel.sortWifiRows(nets, null)
  }
  readonly property var known: rows.filter(function(r) { return r.known })
  readonly property var others: rows.filter(function(r) { return !r.known })

  function networkFor(ssid) {
    var list = status.wifiNetworkObjects || []
    for (var i = 0; i < list.length; i++) if (list[i] && list[i].name === ssid) return list[i]
    return null
  }
  function needsPassword(row) {
    return NetModel.requiresCredentials(row.security, WifiSecurityType.Open, WifiSecurityType.Owe)
  }
  function enterprise(row) {
    return row.security === WifiSecurityType.Wpa2Eap || row.security === WifiSecurityType.WpaEap
  }

  // The network whose password is being asked for, in its row.
  property string askingSsid: ""
  property string failedSsid: ""

  // The network this page started joining, to hear whether it failed.
  property string joiningSsid: ""
  readonly property var failReasons: ({
    NoSecrets: ConnectionFailReason.NoSecrets,
    WifiAuthTimeout: ConnectionFailReason.WifiAuthTimeout,
    WifiNetworkLost: ConnectionFailReason.WifiNetworkLost,
    WifiClientDisconnected: ConnectionFailReason.WifiClientDisconnected,
    WifiClientFailed: ConnectionFailReason.WifiClientFailed
  })
  Connections {
    target: page.joiningSsid !== "" ? page.networkFor(page.joiningSsid) : null
    function onConnectionFailed(reason) {
      var ssid = page.joiningSsid
      var network = page.networkFor(ssid)
      page.joiningSsid = ""
      if (!network || !NetModel.shouldRepromptPassphrase(reason, page.needsPassword({ security: network.security }), page.failReasons)) return
      page.failedSsid = ssid
      page.askingSsid = ssid
    }
    function onConnectedChanged() { if (page.networkFor(page.joiningSsid) && page.networkFor(page.joiningSsid).connected) page.joiningSsid = "" }
  }

  // A tap on the network that is connecting stops it (the control center's
  // Model.cancelConnectScript says how).
  function cancel(row) {
    page.joiningSsid = ""
    page.askingSsid = ""
    cancelProc.command = ["bash", "-c", NetModel.cancelConnectScript, "nmcli-cancel", status.wifiDevice ? String(status.wifiDevice.name || "") : ""]
    cancelProc.running = true
  }
  Process { id: cancelProc }

  function join(row) {
    var network = page.networkFor(row.ssid)
    if (!network || row.connected) return
    if (row.changing) { page.cancel(row); return }
    page.failedSsid = ""
    page.joiningSsid = row.ssid
    if (row.known || !page.needsPassword(row)) {
      network.connect()
      return
    }
    page.askingSsid = page.askingSsid === row.ssid ? "" : row.ssid
  }
  function details(row) {
    if (page.settings) page.settings.push({ kind: "native", page: "wifinetwork", title: row.ssid, ssid: row.ssid })
  }
  function submit(ssid, identity, secret) {
    var network = page.networkFor(ssid)
    if (!network || secret === "") return
    page.askingSsid = ""
    page.failedSsid = ""
    page.joiningSsid = ssid
    if (page.enterprise({ security: network.security })) {
      enterpriseConnect.secret = secret
      enterpriseConnect.command = ["bash", "-c", NetModel.enterpriseConnectScript, "nmcli-eap", ssid, identity]
      enterpriseConnect.running = true
    } else {
      network.connectWithPsk(secret)
    }
  }
  // The control center's 802.1X profile script; the password over stdin,
  // never in argv.
  Process {
    id: enterpriseConnect
    property string secret: ""
    stdinEnabled: true
    onStarted: { write(secret + "\n"); secret = "" }
  }

  function stateOf(row) {
    if (row.changing) return row.connected ? Commons.I18n.t("network.disconnecting") : Commons.I18n.t("network.connecting")
    if (row.connected) return Commons.I18n.t("network.connected")
    if (row.ssid === page.failedSsid) return Commons.I18n.t("network.wrongPassword")
    return ""
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
        label: Commons.I18n.t("settings.wifi")
        isSwitch: true
        switchOn: page.wifiOn
        usable: status.networkManagerAvailable
        onActivated: Networking.wifiEnabled = !Networking.wifiEnabled
      }
      // A wired link, where there is one: it is what the device is on.
      SettingsItem {
        visible: status.kind === "ethernet"
        settings: page.settings
        glyph: "󰈀"
        accent: true
        label: Commons.I18n.t("network.ethernet")
        value: Commons.I18n.t("network.connected")
      }
    }

    Text {
      visible: page.wifiOn && !page.hasWifi
      text: Commons.I18n.t("settings.noWifiDevice")
      color: page.settings ? page.settings.faint : "gray"
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
    }

    Repeater {
      model: page.wifiOn && page.hasWifi ? [
        { title: Commons.I18n.t("network.knownNetworks"), rows: page.known },
        { title: Commons.I18n.t("network.otherNetworks"), rows: page.others }
      ] : []
      SettingsBox {
        id: groupBox
        required property var modelData
        settings: page.settings
        width: column.width
        title: modelData.title
        visible: modelData.rows.length > 0 || modelData.title === Commons.I18n.t("network.otherNetworks")
        SettingsItem {
          visible: groupBox.modelData.rows.length === 0
          settings: page.settings
          first: true
          label: Commons.I18n.t("network.scanningWifi")
          usable: false
        }
        Repeater {
          model: groupBox.modelData.rows
          Column {
            id: entry
            required property var modelData
            required property int index
            width: groupBox.width
            SettingsItem {
              settings: page.settings
              first: entry.index === 0
              glyph: NetModel.wifiIconFor(entry.modelData.signal)
              accent: entry.modelData.connected
              label: entry.modelData.ssid
              value: page.stateOf(entry.modelData)
              trailingGlyph: !entry.modelData.known && page.needsPassword(entry.modelData) ? "󰌾" : ""
              // A known network's page behind its info button; the one in
              // use opens it with a tap anywhere.
              info: entry.modelData.known
              onInfoActivated: page.details(entry.modelData)
              onActivated: entry.modelData.connected ? page.details(entry.modelData) : page.join(entry.modelData)
            }
            PasswordRow {
              visible: page.askingSsid === entry.modelData.ssid
              ssid: entry.modelData.ssid
              withIdentity: page.enterprise(entry.modelData)
            }
          }
        }
      }
    }
  }

  // The password (and, for 802.1X, the identity) under the network it is for.
  component PasswordRow: Item {
    id: ask
    property string ssid: ""
    property bool withIdentity: false
    width: parent ? parent.width : 0
    height: fields.height + Style.space(16)
    onVisibleChanged: {
      identityField.text = ""
      passwordField.text = ""
      if (visible) (withIdentity ? identityField : passwordField).focusInput()
    }
    Column {
      id: fields
      x: Style.space(14)
      y: Style.space(8)
      width: parent.width - 2 * Style.space(14)
      spacing: Style.space(8)
      Field {
        id: identityField
        visible: ask.withIdentity
        placeholder: Commons.I18n.t("network.identity")
        onAccepted: passwordField.focusInput()
      }
      Row {
        width: parent.width
        spacing: Style.space(8)
        Field {
          id: passwordField
          width: parent.width - joinButton.width - parent.spacing
          placeholder: Commons.I18n.t("network.passphrase")
          secret: true
          onAccepted: page.submit(ask.ssid, identityField.text, text)
        }
        Rectangle {
          id: joinButton
          width: joinText.width + Style.space(24)
          height: passwordField.height
          color: page.settings ? page.settings.accent : "white"
          Text {
            id: joinText
            anchors.centerIn: parent
            text: Commons.I18n.t("network.connect")
            color: Commons.Color.background
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }
          TapHandler { onTapped: page.submit(ask.ssid, identityField.text, passwordField.text) }
        }
      }
    }
  }

  component Field: Rectangle {
    id: field
    property alias text: input.text
    property string placeholder: ""
    property bool secret: false
    signal accepted()
    function focusInput() { input.forceActiveFocus() }
    width: parent ? parent.width : 0
    height: Style.space(38)
    color: "transparent"
    border.width: 1
    border.color: input.activeFocus && page.settings ? Util.alpha(page.settings.accent, 0.7) : (page.settings ? page.settings.line : "gray")
    TextInput {
      id: input
      x: Style.space(10)
      width: parent.width - 2 * x
      anchors.verticalCenter: parent.verticalCenter
      color: page.settings ? page.settings.text : "white"
      echoMode: field.secret ? TextInput.Password : TextInput.Normal
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      clip: true
      onAccepted: field.accepted()
      Keys.onEscapePressed: function(event) { page.askingSsid = ""; event.accepted = true }
      Text {
        visible: input.text === ""
        text: field.placeholder
        color: page.settings ? page.settings.faint : "gray"
        font: input.font
      }
    }
  }
}
