// Keyboard shortcuts from labwc's rc.xml, named for people: what each does,
// in groups, and its keys as they are written on a keyboard. A binding the
// table does not know shows its command, so an own one is still listed.

// <keybind key="W-S-b"><action name="Execute" command="..." /></keybind>
function parse(text) {
  var out = []
  var source = String(text || "").replace(/<!--[\s\S]*?-->/g, "")
  var re = /<keybind\b([^>]*?)(\/>|>([\s\S]*?)<\/keybind>)/g
  var m
  while ((m = re.exec(source)) !== null) {
    var key = attr(m[1], "key")
    if (!key) continue
    var actions = []
    var body = m[3] || ""
    var are = /<action\b([^>]*?)\/?>/g
    var a
    while ((a = are.exec(body)) !== null) {
      actions.push({ name: attr(a[1], "name"), command: unescape(attr(a[1], "command")),
                     direction: attr(a[1], "direction"), menu: attr(a[1], "menu") })
    }
    out.push({ key: key, actions: actions })
  }
  return out
}

function attr(text, name) {
  var m = new RegExp("\\b" + name + "=\"([^\"]*)\"").exec(text)
  return m ? m[1] : ""
}

function unescape(text) {
  return String(text).replace(/&quot;/g, "\"").replace(/&apos;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&")
}

// What a binding does: { group, label } (i18n keys), or null for one that is
// there only to swallow a key (Execute /usr/bin/true).
//   groups: shell, apps, windows, screenshots, hardware, other
var COMMANDS = [
  [/omarchy\.dock apps$/, "shell", "shortcuts.launcher"],
  [/omarchy\.controlcenter toggle/, "shell", "shortcuts.controlCenter"],
  [/omarchy\.notificationcenter toggle/, "shell", "shortcuts.notificationCenter"],
  [/toggle omarchy\.audio\b/, "shell", "shortcuts.audio"],
  [/toggle omarchy\.bluetooth\b/, "shell", "shortcuts.bluetooth"],
  [/toggle omarchy\.monitor\b/, "shell", "shortcuts.display"],
  [/toggle omarchy\.network\b/, "shell", "shortcuts.network"],
  [/toggle omarchy\.power\b/, "shell", "shortcuts.power"],
  [/omarchy\.menu .*"system"/, "shell", "shortcuts.systemMenu"],
  [/omarchy\.menu .*"root"/, "shell", "shortcuts.menu"],
  [/omarchy-toggle-bar\b/, "shell", "shortcuts.bar"],
  [/\bfoot\b|omarchy-launch-terminal/, "apps", "shortcuts.terminal"],
  [/\bfirefox\b|omarchy-launch-browser/, "apps", "shortcuts.browser"],
  [/omactivity|\bbtop\b/, "apps", "shortcuts.activity"],
  [/\bgrim\b|omarchy-capture-screenshot/, "screenshots", "shortcuts.screenshot"],
  [/omarchy-volume raise/, "hardware", "shortcuts.volumeUp"],
  [/omarchy-volume lower/, "hardware", "shortcuts.volumeDown"],
  [/omarchy-volume mute/, "hardware", "shortcuts.mute"],
  [/omarchy-brightness-display .*\+/, "hardware", "shortcuts.brightnessUp"],
  [/omarchy-brightness-display .*-\d/, "hardware", "shortcuts.brightnessDown"],
  [/monitor-scaling up/, "windows", "shortcuts.scaleUp"],
  [/monitor-scaling down/, "windows", "shortcuts.scaleDown"]
]
var ACTIONS = {
  Close: "shortcuts.close",
  ToggleFullscreen: "shortcuts.fullscreen",
  ToggleMaximize: "shortcuts.maximize",
  ToggleOverview: "shortcuts.overview",
  NextWindow: "shortcuts.switchWindows",
  PreviousWindow: "shortcuts.switchWindowsBack",
  NextWindowImmediate: "shortcuts.nextWindow",
  PreviousWindowImmediate: "shortcuts.previousWindow",
  HideCursor: "shortcuts.hideCursor",
  Iconify: "shortcuts.minimize",
  ShowMenu: "shortcuts.menu"
}

function describe(binding) {
  var first = binding.actions[0]
  if (!first) return null
  if (first.name === "Execute") {
    var command = first.command
    if (/^\s*(\/usr\/bin\/)?true\s*$/.test(command)) return null
    for (var i = 0; i < COMMANDS.length; i++) {
      // A window command (display scale) after the window actions.
      if (COMMANDS[i][0].test(command)) return { group: COMMANDS[i][1], label: COMMANDS[i][2], rank: COMMANDS[i][1] === "windows" ? 300 + i : i }
    }
    return { group: "other", label: "", command: command, rank: 1000 }
  }
  if (first.name === "SnapToEdge") {
    var dir = String(first.direction || "")
    var dirs = ["up", "down", "left", "right"]
    return { group: "windows", label: "shortcuts.snap" + dir.charAt(0).toUpperCase() + dir.slice(1), direction: dir,
             rank: 200 + Object.keys(ACTIONS).length + Math.max(0, dirs.indexOf(dir)) }
  }
  if (ACTIONS[first.name]) return { group: "windows", label: ACTIONS[first.name], rank: 200 + Object.keys(ACTIONS).indexOf(first.name) }
  return { group: "other", label: "", command: first.name, rank: 1000 }
}

var GROUPS = ["shell", "apps", "windows", "screenshots", "hardware", "other"]

// The bindings in their groups: [{ group, rows: [{ keys, label, command, direction }] }].
// Two keys for one thing (Super_L, Super_R) are one row.
function groups(text) {
  var bindings = parse(text)
  var byGroup = {}
  for (var i = 0; i < bindings.length; i++) {
    var d = describe(bindings[i])
    if (!d) continue
    var rows = byGroup[d.group] || (byGroup[d.group] = [])
    var same = null
    for (var j = 0; j < rows.length; j++) {
      if (rows[j].label === d.label && rows[j].command === (d.command || "") && rows[j].direction === (d.direction || "")) same = rows[j]
    }
    var keys = keyLabel(bindings[i].key)
    if (same) { if (same.keys.indexOf(keys) < 0) same.keys.push(keys); continue }
    rows.push({ keys: [keys], label: d.label, command: d.command || "", direction: d.direction || "", rank: d.rank })
  }
  // In the table's order (the control center beside the notification
  // center), not the file's; what the table does not know, as it comes.
  for (var key in byGroup) byGroup[key].sort(function(a, b) { return a.rank - b.rank })
  var out = []
  for (var g = 0; g < GROUPS.length; g++) if (byGroup[GROUPS[g]]) out.push({ group: GROUPS[g], rows: byGroup[GROUPS[g]] })
  return out
}

// "W-S-b" → "Super Shift B"; keysyms as they read.
var MODIFIERS = { W: "Super", S: "Shift", C: "Ctrl", A: "Alt", M: "Alt", H: "Hyper", L: "Mod5" }
var KEYS = {
  Super_L: "Super", Super_R: "Super", Return: "Return", space: "Space", Escape: "Esc",
  Tab: "Tab", slash: "/", Print: "Print", Up: "↑", Down: "↓", Left: "←", Right: "→",
  XF86AudioRaiseVolume: "Volume Up", XF86AudioLowerVolume: "Volume Down", XF86AudioMute: "Mute",
  XF86MonBrightnessUp: "Brightness Up", XF86MonBrightnessDown: "Brightness Down", XF86HomePage: "Home"
}
function keyLabel(key) {
  var parts = String(key).split("-")
  var last = parts.pop()
  var out = []
  for (var i = 0; i < parts.length; i++) out.push(MODIFIERS[parts[i]] || parts[i])
  out.push(KEYS[last] || (last.length === 1 ? last.toUpperCase() : last))
  return out.join(" ")
}

if (typeof module !== "undefined") module.exports = { parse: parse, describe: describe, groups: groups, keyLabel: keyLabel }
