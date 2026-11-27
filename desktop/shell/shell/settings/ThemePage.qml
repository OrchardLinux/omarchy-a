import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import "SettingsModel.js" as Model

// The installed themes, each drawn in its own colours (its colors.toml), the
// current one marked. A tap switches to it, as the menu's Theme picker does.
Item {
  id: page

  property var settings: null
  // Its data read: Settings shows it (and slides it in) only then.
  property bool ready: false
  property var themes: []
  property string current: ""

  width: parent ? parent.width : 0
  height: grid.height

  readonly property int columns: Math.max(2, Math.floor((width + gap) / (Style.space(170) + gap)))
  readonly property int gap: Style.space(14)
  readonly property real cell: (width - gap * (columns - 1)) / columns

  // name, then the colours the tile needs, one theme a line. The user's
  // themes first, as the menu's switcher lists them.
  Process {
    id: lister
    running: true
    command: ["bash", "-lc", [
      "cat ~/.local/state/omarchy/current/theme.name 2>/dev/null; echo",
      "for dir in ~/.config/omarchy/themes/*/ \"$OMARCHY_PATH\"/themes/*/; do",
      "  [[ -f $dir/colors.toml ]] || continue",
      "  name=${dir%/}; name=${name##*/}",
      // The wallpaper a switch to it starts on: omarchy-theme-set's first.
      "  bg=$(find -L \"$dir/backgrounds\" -maxdepth 1 -type f ! -name '._*' \\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \\) -printf '%f\\n' 2>/dev/null | sort | head -1)",
      "  [[ -n $bg ]] && bg=${dir}backgrounds/$bg",
      "  printf 't\\t%s\\t%s\\t%s\\n' \"$name\" \"$(tr '\\n' ';' < \"$dir/colors.toml\")\" \"$bg\"",
      "done"
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
        if (parts[0] !== "t" || !parts[1] || seen[parts[1]]) continue
        seen[parts[1]] = true
        out.push({ slug: parts[1], name: Model.displayName(parts[1]), colors: Model.parseColors((parts[2] || "").split(";").join("\n")), wallpaper: parts[3] || "" })
      }
      page.themes = out
      page.ready = true
    }
  }

  function pick(theme) {
    page.current = theme.slug
    if (settings) settings.run("omarchy-theme-set " + Util.shellQuote(theme.slug))
  }

  Grid {
    id: grid
    width: page.width
    columns: page.columns
    columnSpacing: page.gap
    rowSpacing: page.gap
    Repeater {
      model: page.themes
      Column {
        id: tile
        required property var modelData
        readonly property bool isCurrent: modelData.slug === page.current
        width: page.cell
        spacing: Style.space(6)
        Rectangle {
          width: parent.width
          height: Math.round(width * 0.56)
          color: tile.modelData.colors.background || "#000000"
          // The theme's own wallpaper behind, and over it a window in its
          // colours: the desktop a switch to it starts on.
          Image {
            anchors.fill: parent
            anchors.margins: parent.border.width
            visible: status === Image.Ready
            source: tile.modelData.wallpaper ? Util.fileUrl(tile.modelData.wallpaper) : ""
            sourceSize.width: Math.ceil(width * 2)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
          }
          Rectangle {
            id: sample
            x: Style.space(10)
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Style.space(10)
            width: Math.max(swatches.width, aa.width) + Style.space(20)
            height: aa.height + swatches.height + Style.space(24)
            color: tile.modelData.colors.background || "#000000"
            Text {
              id: aa
              x: Style.space(10); y: Style.space(8)
              text: "Aa"
              color: tile.modelData.colors.foreground || "#ffffff"
              font.family: Style.font.family
              font.pixelSize: Style.font.title
              font.bold: true
            }
            Row {
              id: swatches
              x: Style.space(10)
              anchors.bottom: parent.bottom
              anchors.bottomMargin: Style.space(10)
              spacing: Style.space(4)
              Repeater {
                model: Model.swatchesOf(tile.modelData.colors)
                Rectangle { required property var modelData; width: Style.space(13); height: width; color: modelData }
              }
            }
          }
          // The frame over the picture, so the current one's mark shows.
          Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: tile.isCurrent ? 2 : 1
            border.color: tile.isCurrent ? (settings ? settings.accent : "white") : (settings ? settings.line : "gray")
          }
        }
        Item {
          width: parent.width
          height: nameText.height
          Text {
            id: nameText
            width: parent.width - check.width
            text: tile.modelData.name
            color: settings ? (tile.isCurrent ? settings.text : settings.dim) : "white"
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            font.bold: tile.isCurrent
            elide: Text.ElideRight
          }
          Text {
            id: check
            anchors.right: parent.right
            visible: tile.isCurrent
            text: "✓"
            color: settings ? settings.accent : "white"
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }
        }
        TapHandler { onTapped: page.pick(tile.modelData) }
      }
    }
  }
}
