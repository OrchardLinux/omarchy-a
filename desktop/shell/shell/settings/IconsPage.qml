import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import "SettingsModel.js" as Model

// The icon sets, each shown by the preview it ships (Original, which draws
// nothing of its own, by name), the current one marked. A tap applies it, as
// the menu's Icons picker does.
Item {
  id: page

  property var settings: null
  // Its data read: Settings shows it (and slides it in) only then.
  property bool ready: false
  property var sets: []
  property string current: ""

  width: parent ? parent.width : 0
  height: grid.height

  readonly property int gap: Style.space(14)
  // Wide tiles: a set is a sheet of small drawings, which a narrow tile
  // shrinks past seeing. One a row on a phone.
  readonly property int columns: Math.max(1, Math.floor((width + gap) / (Style.space(300) + gap)))
  readonly property real cell: (width - gap * (columns - 1)) / columns

  Process {
    id: lister
    running: true
    command: ["bash", "-lc", [
      "omarchy-icons-current --id 2>/dev/null; echo",
      "for dir in ~/.config/omarchy/icons/*/ \"$OMARCHY_PATH\"/icons/*/; do",
      "  [[ -d $dir ]] || continue",
      "  name=${dir%/}; name=${name##*/}",
      "  preview=; [[ -f $dir/preview.png ]] && preview=$dir/preview.png",
      "  printf 's\\t%s\\t%s\\n' \"$name\" \"$preview\"",
      "done",
      "printf 's\\toriginal\\t\\n'"
    ].join("\n")]
    property string collected: ""
    stdout: SplitParser { onRead: function(data) { lister.collected += data + "\n" } }
    onExited: {
      var lines = lister.collected.split("\n")
      page.current = lines[0].trim()
      var seen = {}
      var out = []
      for (var i = 1; i < lines.length; i++) {
        var parts = lines[i].split("\t")
        if (parts[0] !== "s" || !parts[1] || seen[parts[1]]) continue
        seen[parts[1]] = true
        out.push({ id: parts[1], name: Model.displayName(parts[1]), preview: parts[2] || "" })
      }
      page.sets = out
      page.ready = true
    }
  }

  function pick(set) {
    page.current = set.id
    if (settings) settings.run("omarchy-icons-set " + Util.shellQuote(set.id))
  }

  Grid {
    id: grid
    width: page.width
    columns: page.columns
    columnSpacing: page.gap
    rowSpacing: page.gap
    Repeater {
      model: page.sets
      Column {
        id: tile
        required property var modelData
        readonly property bool isCurrent: modelData.id === page.current
        width: page.cell
        spacing: Style.space(6)
        Item {
          width: parent.width
          height: Math.round(width * 0.56)
          clip: true
          Rectangle { anchors.fill: parent; color: settings ? settings.fill : "black" }
          // The sheet keeps its drawings to the middle of its frame, with
          // room around them; a little larger, they fill the tile to its edge
          // without losing a row.
          Image {
            anchors.centerIn: parent
            width: parent.width * 1.15
            height: parent.height * 1.15
            visible: tile.modelData.preview !== ""
            source: tile.modelData.preview ? Util.fileUrl(tile.modelData.preview) : ""
            sourceSize.width: Math.round(page.cell * 2)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
          }
          Text {
            visible: tile.modelData.preview === ""
            anchors.centerIn: parent
            text: tile.modelData.name
            color: settings ? settings.dim : "gray"
            font.family: Style.font.family
            font.pixelSize: Style.font.subtitle
          }
          // The frame over the picture.
          Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: tile.isCurrent ? 2 : 1
            border.color: tile.isCurrent ? (settings ? settings.accent : "white") : (settings ? settings.line : "gray")
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
