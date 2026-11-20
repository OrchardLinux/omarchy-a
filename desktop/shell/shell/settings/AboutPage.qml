import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons

// This device as the system reports it: model, system, version, kernel,
// memory and storage. Nothing here is typed in; a line the system cannot
// answer is left out.
Item {
  id: page

  property var settings: null
  property var facts: []

  width: parent ? parent.width : 0
  height: box.height

  Process {
    id: reader
    running: true
    command: ["bash", "-lc", [
      "model=$(tr -d '\\0' < /proc/device-tree/model 2>/dev/null); [[ -n $model ]] || model=$(cat /sys/class/dmi/id/product_name 2>/dev/null)",
      "printf 'device\\t%s\\n' \"$model\"",
      "printf 'name\\t%s\\n' \"$(cat /etc/hostname 2>/dev/null || uname -n)\"",
      "printf 'system\\t%s\\n' \"$(. /etc/os-release 2>/dev/null; echo \"$PRETTY_NAME\")\"",
      "printf 'version\\t%s\\n' \"$(omarchy-version 2>/dev/null || cat \"$OMARCHY_PATH/version\" 2>/dev/null)\"",
      "printf 'kernel\\t%s\\n' \"$(uname -r)\"",
      "printf 'memory\\t%s\\n' \"$(awk '/^MemTotal:/ { printf \"%.1f GB\", $2 / 1048576 }' /proc/meminfo)\"",
      "printf 'storage\\t%s\\n' \"$(df -B1 / 2>/dev/null | awk 'NR == 2 { printf \"%.0f GB of %.0f GB free\", $4 / 1e9, $2 / 1e9 }')\""
    ].join("\n")]
    property string collected: ""
    stdout: SplitParser { onRead: function(data) { reader.collected += data + "\n" } }
    onExited: {
      var labels = {
        device: "settings.aboutDevice", name: "settings.aboutName", system: "settings.aboutSystem",
        version: "settings.aboutVersion", kernel: "settings.aboutKernel", memory: "settings.aboutMemory",
        storage: "settings.aboutStorage"
      }
      var out = []
      var lines = reader.collected.split("\n")
      for (var i = 0; i < lines.length; i++) {
        var parts = lines[i].split("\t")
        if (!labels[parts[0]] || !parts[1] || !parts[1].trim()) continue
        out.push({ label: Commons.I18n.t(labels[parts[0]]), value: parts[1].trim() })
      }
      page.facts = out
    }
  }

  Rectangle {
    id: box
    width: page.width
    height: factColumn.height + 2
    color: settings ? settings.fill : "transparent"
    border.width: 1
    border.color: settings ? settings.line : "gray"
    Column {
      id: factColumn
      x: 1; y: 1
      width: parent.width - 2
      Repeater {
        model: page.facts
        Item {
          required property var modelData
          required property int index
          width: factColumn.width
          height: settings ? settings.rowHeight : 40
          Rectangle {
            visible: parent.index > 0
            width: parent.width; height: 1
            color: Util.alpha(settings ? settings.text : "white", 0.07)
          }
          Text {
            x: Style.space(14)
            anchors.verticalCenter: parent.verticalCenter
            text: parent.modelData.label
            color: settings ? settings.text : "white"
            font.family: Style.font.family
            font.pixelSize: Style.font.subtitle
          }
          Text {
            anchors.right: parent.right
            anchors.rightMargin: Style.space(14)
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, parent.width * 0.6)
            horizontalAlignment: Text.AlignRight
            text: parent.modelData.value
            color: settings ? settings.dim : "gray"
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
          }
        }
      }
    }
  }
}
