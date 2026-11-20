import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import "../plugins/status" as StatusParts

// Display: brightness (and following the light, where there is a sensor) and
// rotation lock, through the commands the control center uses; the menu's
// display rows (Night Light, Monitors, ...) follow under it.
Item {
  id: page

  property var settings: null

  width: parent ? parent.width : 0
  height: column.height

  StatusParts.RotationLock { id: rotation }

  property int brightness: -1     // percent, -1 until read (or no backlight)
  property bool autoAvailable: false
  property bool autoOn: false

  Process {
    id: brightnessRead
    running: true
    command: ["omarchy-brightness-display"]
    stdout: StdioCollector {
      onStreamFinished: {
        var value = parseInt(String(text).trim(), 10)
        page.brightness = isNaN(value) ? -1 : value
      }
    }
  }
  Process {
    id: autoRead
    running: true
    command: ["bash", "-c", "omarchy-auto-brightness available && omarchy-auto-brightness status"]
    stdout: StdioCollector {
      onStreamFinished: {
        page.autoAvailable = /auto-brightness: (on|off)/.test(text)
        page.autoOn = /auto-brightness: on/.test(text)
      }
    }
  }

  // As the control center sets it: no OSD, and one command for a burst of moves.
  function setBrightness(value) {
    page.brightness = Math.max(1, Math.min(100, Math.round(value * 100)))
    brightnessSet.restart()
  }
  Timer {
    id: brightnessSet
    interval: 60
    onTriggered: Quickshell.execDetached(["omarchy-brightness-display", "--no-osd", page.brightness + "%"])
  }

  Column {
    id: column
    width: page.width
    spacing: Style.space(14)

    SettingsBox {
      settings: page.settings
      width: parent.width
      title: Commons.I18n.t("settings.brightness")
      visible: page.brightness >= 0
      SettingsSlider {
        settings: page.settings
        first: true
        glyph: "󰃞"
        level: page.brightness / 100
        onMoved: function(value) { page.setBrightness(value) }
      }
      SettingsItem {
        visible: page.autoAvailable
        settings: page.settings
        label: Commons.I18n.t("settings.autoBrightness")
        isSwitch: true
        switchOn: page.autoOn
        onActivated: {
          page.autoOn = !page.autoOn
          Quickshell.execDetached(["omarchy-auto-brightness", page.autoOn ? "on" : "off"])
        }
      }
    }

    SettingsBox {
      settings: page.settings
      width: parent.width
      SettingsItem {
        settings: page.settings
        first: true
        label: Commons.I18n.t("settings.rotationLock")
        isSwitch: true
        switchOn: rotation.locked
        onActivated: {
          Quickshell.execDetached(["omarchy-rotation-lock", rotation.locked ? "off" : "on"])
          rotation.locked = !rotation.locked
        }
      }
    }
  }
}
