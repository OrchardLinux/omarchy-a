import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons

// The current theme's backgrounds and the person's own for it, as the
// menu's Background picker offers them; the current one marked. Thumbnails
// are decoded small and not cached, so the page costs little and gives it
// back when it closes.
Item {
  id: page

  property var settings: null
  property var images: []
  property string current: ""

  width: parent ? parent.width : 0
  height: grid.height

  readonly property int gap: Style.space(14)
  readonly property int columns: Math.max(2, Math.floor((width + gap) / (Style.space(200) + gap)))
  readonly property real cell: (width - gap * (columns - 1)) / columns

  Process {
    id: lister
    running: true
    command: ["bash", "-lc", [
      "readlink -f ~/.local/state/omarchy/current/background 2>/dev/null; echo",
      "theme=$(cat ~/.local/state/omarchy/current/theme.name 2>/dev/null)",
      "for dir in ~/.local/state/omarchy/current/theme/backgrounds \"$HOME/.config/omarchy/backgrounds/$theme\"; do",
      "  [[ -d $dir ]] || continue",
      "  find -L \"$dir\" -maxdepth 1 -type f \\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' -o -iname '*.gif' -o -iname '*.bmp' -o -iname '*.mp4' -o -iname '*.webm' -o -iname '*.mov' -o -iname '*.mkv' \\) -print 2>/dev/null | sort | while read -r f; do printf 'i\\t%s\\t%s\\n' \"$f\" \"$(readlink -f \"$f\")\"; done",
      "done"
    ].join("\n")]
    property string collected: ""
    stdout: SplitParser { onRead: function(data) { lister.collected += data + "\n" } }
    onExited: {
      var lines = lister.collected.split("\n")
      page.current = lines[0].trim()
      var out = []
      for (var i = 1; i < lines.length; i++) {
        var parts = lines[i].split("\t")
        if (parts[0] !== "i" || !parts[1]) continue
        var file = parts[1]
        var name = file.replace(/^.*\//, "").replace(/\.[^.]*$/, "").replace(/^\d+-/, "").replace(/-/g, " ")
        out.push({ path: file, real: parts[2] || file, name: name, video: /\.(mp4|webm|mov|mkv)$/i.test(file) })
      }
      page.images = out
    }
  }

  function pick(image) {
    page.current = image.real
    if (settings) settings.run("omarchy-theme-bg-set " + Util.shellQuote(image.path))
  }

  Text {
    visible: lister.running === false && page.images.length === 0
    text: Commons.I18n.t("settings.noBackgrounds")
    color: settings ? settings.faint : "gray"
    font.family: Style.font.family
    font.pixelSize: Style.font.subtitle
  }

  Grid {
    id: grid
    width: page.width
    columns: page.columns
    columnSpacing: page.gap
    rowSpacing: page.gap
    Repeater {
      model: page.images
      Column {
        id: tile
        required property var modelData
        readonly property bool isCurrent: modelData.real === page.current
        width: page.cell
        spacing: Style.space(6)
        Rectangle {
          width: parent.width
          height: Math.round(width * 0.62)
          color: settings ? settings.fill : "black"
          border.width: tile.isCurrent ? 2 : 1
          border.color: tile.isCurrent ? (settings ? settings.accent : "white") : (settings ? settings.line : "gray")
          clip: true
          Image {
            anchors.fill: parent
            anchors.margins: parent.border.width
            visible: !tile.modelData.video
            source: tile.modelData.video ? "" : Util.fileUrl(tile.modelData.path)
            sourceSize.width: Math.round(page.cell * 1.5)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
          }
          Text {
            visible: tile.modelData.video
            anchors.centerIn: parent
            text: ""
            color: settings ? settings.faint : "gray"
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.display
          }
        }
        Text {
          width: parent.width
          text: tile.modelData.name
          color: settings ? (tile.isCurrent ? settings.text : settings.dim) : "white"
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: tile.isCurrent
          elide: Text.ElideRight
        }
        TapHandler { onTapped: page.pick(tile.modelData) }
      }
    }
  }
}
