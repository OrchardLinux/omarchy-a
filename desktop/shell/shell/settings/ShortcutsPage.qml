import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import "ShortcutsModel.js" as Shortcuts

// Keyboard Shortcuts: what labwc's rc.xml binds, read from the user's own
// file (so a binding added there shows too), named and grouped; read only.
Item {
  id: page

  property var settings: null

  width: parent ? parent.width : 0
  height: column.height

  FileView {
    id: rc
    path: (Quickshell.env("HOME") || "") + "/.config/labwc/rc.xml"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
  }
  readonly property var groups: Shortcuts.groups(rc.text())

  Column {
    id: column
    width: page.width
    spacing: Style.space(14)

    Repeater {
      model: page.groups
      SettingsBox {
        id: box
        required property var modelData
        settings: page.settings
        width: column.width
        title: Commons.I18n.t("shortcuts.group." + modelData.group)
        Repeater {
          model: box.modelData.rows
          SettingsItem {
            required property var modelData
            required property int index
            settings: page.settings
            first: index === 0
            label: modelData.label ? Commons.I18n.t(modelData.label) : modelData.command
            value: modelData.keys.join("  ·  ")
          }
        }
      }
    }

    Text {
      visible: page.groups.length === 0
      text: Commons.I18n.t("shortcuts.none")
      color: page.settings ? page.settings.faint : "gray"
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
    }
  }
}
