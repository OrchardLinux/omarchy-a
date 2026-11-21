import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons

// Date & Time: whether the clock sets itself (NTP) and the time zone, through
// timedatectl. The tablet runs no polkit agent: a polkit rule lets its
// active local session change these two without a password
// (system/overlay/etc/polkit-1/rules.d/60-omarchy-tablet-time.rules).
Item {
  id: page

  property var settings: null

  width: parent ? parent.width : 0
  height: column.height

  property string zone: ""
  property bool automatic: false
  property bool canAutomatic: false
  property bool busy: false

  function read() { reader.running = true }
  Component.onCompleted: read()
  Process {
    id: reader
    command: ["timedatectl", "show", "-p", "Timezone", "-p", "NTP", "-p", "CanNTP"]
    stdout: StdioCollector {
      onStreamFinished: {
        var lines = String(text).split("\n")
        for (var i = 0; i < lines.length; i++) {
          var at = lines[i].indexOf("=")
          if (at < 0) continue
          var key = lines[i].slice(0, at), value = lines[i].slice(at + 1)
          if (key === "Timezone") page.zone = value
          else if (key === "NTP") page.automatic = value === "yes"
          else if (key === "CanNTP") page.canAutomatic = value === "yes"
        }
      }
    }
  }
  Process {
    id: writer
    onExited: { page.busy = false; page.read() }
  }
  function setAutomatic(on) {
    if (writer.running) return
    page.busy = true
    page.automatic = on
    writer.command = ["timedatectl", "set-ntp", on ? "true" : "false"]
    writer.running = true
  }

  // The time now, to the minute, in the zone set.
  property date now: new Date()
  Timer { interval: 1000; running: true; repeat: true; onTriggered: page.now = new Date() }

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
        label: Commons.I18n.t("settings.setAutomatically")
        isSwitch: true
        switchOn: page.automatic
        usable: page.canAutomatic && !page.busy
        onActivated: page.setAutomatic(!page.automatic)
      }
      SettingsItem {
        settings: page.settings
        label: Commons.I18n.t("settings.timeZone")
        value: page.zone.replace(/_/g, " ")
        opens: true
        onActivated: if (page.settings) page.settings.push({ kind: "native", page: "timezone", title: Commons.I18n.t("settings.timeZone") })
      }
    }

    SettingsBox {
      settings: page.settings
      width: parent.width
      SettingsItem {
        settings: page.settings
        first: true
        label: Commons.I18n.t("settings.timeNow")
        value: page.now.toLocaleDateString(Qt.locale(), "d MMMM yyyy") + ", " + page.now.toLocaleTimeString(Qt.locale(), Locale.ShortFormat)
      }
    }
  }
}
