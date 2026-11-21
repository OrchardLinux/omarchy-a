import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons

// The time zones: a search over all of them, and under it the regions (Africa,
// America, ...), each opening its own list, so no page holds all six hundred
// rows at once. A pick sets it (timedatectl) and goes back to Date & Time.
Item {
  id: page

  property var settings: null
  // The region this page lists, or "" for the regions and the search.
  readonly property string region: settings && settings.top && settings.top.region ? settings.top.region : ""

  width: parent ? parent.width : 0
  height: column.height

  property var zones: []
  // The list read: Settings shows the page (and slides it in) only then.
  readonly property bool ready: zones.length > 0
  property string current: ""
  Process {
    running: true
    command: ["timedatectl", "list-timezones"]
    // The world's regions only, and UTC: the list's old aliases (US/Pacific,
    // Brazil/East, Etc/GMT+3, ...) name zones the regions already have.
    stdout: StdioCollector {
      onStreamFinished: page.zones = String(text).split("\n").filter(function(z) {
        return z === "UTC" || page.regionNames.indexOf(z.split("/")[0]) >= 0 && z.indexOf("/") > 0
      })
    }
  }
  Process {
    running: true
    command: ["timedatectl", "show", "-p", "Timezone", "--value"]
    stdout: StdioCollector { onStreamFinished: page.current = String(text).trim() }
  }

  // "America/Argentina/Buenos_Aires": the city, then where it is.
  function city(zone) { var p = zone.split("/"); return p[p.length - 1].replace(/_/g, " ") }
  function where(zone) { var p = zone.split("/"); return p.slice(0, -1).join(", ").replace(/_/g, " ") }

  readonly property var regionNames: ["Africa", "America", "Antarctica", "Arctic", "Asia", "Atlantic", "Australia", "Europe", "Indian", "Pacific"]
  readonly property var regions: {
    var seen = {}, out = []
    for (var i = 0; i < zones.length; i++) {
      var at = zones[i].indexOf("/")
      var r = at < 0 ? "" : zones[i].slice(0, at)
      if (r === "" || seen[r]) continue
      seen[r] = true
      out.push(r)
    }
    return out
  }
  property string query: ""
  readonly property var rows: {
    var q = query.trim().toLowerCase().replace(/ /g, "_")
    if (region !== "") return zones.filter(function(z) { return z.indexOf(region + "/") === 0 })
    if (q === "") return []
    // The city's start first, then anywhere in the name; at most 60.
    var first = [], rest = []
    for (var i = 0; i < zones.length; i++) {
      var z = zones[i].toLowerCase(), c = page.city(zones[i]).toLowerCase().replace(/ /g, "_")
      if (c.indexOf(q) === 0) first.push(zones[i])
      else if (z.indexOf(q) >= 0) rest.push(zones[i])
    }
    return first.concat(rest).slice(0, 60)
  }

  Process {
    id: writer
    stderr: StdioCollector { onStreamFinished: if (text !== "") console.warn("settings: time zone:", text.trim()) }
    onExited: function(code) {
      if (code !== 0) return
      Commons.TimeZone.changed()
      if (page.settings) page.settings.backTo("datetime")
    }
  }
  function choose(zone) {
    if (writer.running || zone === page.current) return
    writer.command = ["timedatectl", "set-timezone", zone]
    writer.running = true
  }

  Column {
    id: column
    width: page.width
    spacing: Style.space(14)

    // The search, on the first page only.
    Rectangle {
      visible: page.region === ""
      width: parent.width
      height: Style.space(40)
      color: "transparent"
      border.width: 1
      border.color: input.activeFocus && page.settings ? Util.alpha(page.settings.accent, 0.7) : (page.settings ? page.settings.line : "gray")
      TextInput {
        id: input
        x: Style.space(12)
        width: parent.width - 2 * x
        anchors.verticalCenter: parent.verticalCenter
        color: page.settings ? page.settings.text : "white"
        font.family: Style.font.family
        font.pixelSize: Style.font.subtitle
        clip: true
        onTextChanged: page.query = text
        Keys.onEscapePressed: function(event) {
          if (text !== "") { text = ""; event.accepted = true } else event.accepted = false
        }
        Text {
          visible: input.text === ""
          text: Commons.I18n.t("settings.searchTimeZones")
          color: page.settings ? page.settings.faint : "gray"
          font: input.font
        }
      }
    }

    // Matches, or a region's zones.
    SettingsBox {
      settings: page.settings
      width: parent.width
      visible: page.rows.length > 0
      Repeater {
        model: page.rows
        SettingsItem {
          required property var modelData
          required property int index
          settings: page.settings
          first: index === 0
          label: page.city(modelData)
          detail: page.region === "" ? page.where(modelData) : (page.where(modelData) !== page.region ? page.where(modelData).slice(page.region.length + 2) : "")
          checked: modelData === page.current
          onActivated: page.choose(modelData)
        }
      }
    }
    Text {
      visible: page.region === "" && page.query.trim() !== "" && page.rows.length === 0
      text: Commons.I18n.t("settings.noResults")
      color: page.settings ? page.settings.faint : "gray"
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
    }

    // The regions, while not searching; UTC first.
    SettingsBox {
      settings: page.settings
      width: parent.width
      visible: page.region === "" && page.query.trim() === ""
      SettingsItem {
        settings: page.settings
        first: true
        label: "UTC"
        checked: page.current === "UTC"
        onActivated: page.choose("UTC")
      }
      Repeater {
        model: page.regions
        SettingsItem {
          required property var modelData
          required property int index
          settings: page.settings
          label: modelData.replace(/_/g, " ")
          value: page.current.indexOf(modelData + "/") === 0 ? page.city(page.current) : ""
          opens: true
          onActivated: if (page.settings) page.settings.push({ kind: "native", page: "timezone", title: modelData.replace(/_/g, " "), region: modelData })
        }
      }
    }
  }
}
