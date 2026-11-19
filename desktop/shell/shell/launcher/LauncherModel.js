.pragma library

// Pure helpers for the launcher: layout numbers, grouping and time words.
// Kept apart from Launcher.qml so they read (and test) without a window.

// Columns of the app grid: 8 in landscape, 6 in portrait, 4 on a phone
// (6 on a phone held sideways).
function columnsFor(width, height, phone) {
  if (phone) return width > height ? 6 : 4
  return width > height ? 8 : 6
}

// A screen narrower than this is a phone's.
var PHONE_WIDTH = 600

function isPhone(width, height) {
  return Math.min(width, height) < PHONE_WIDTH
}

// The menu's System list as the session actions: its children in menu order,
// without About (it belongs to Settings) and without Alt stand-ins.
function sessionIds(itemOrder, items, altIds) {
  var out = []
  for (var i = 0; i < itemOrder.length; i++) {
    var entry = items[itemOrder[i]]
    if (!entry || entry.parent !== "system" || entry.kind !== "action") continue
    if (entry.id === "system.about" || altIds[entry.id]) continue
    out.push(entry.id)
  }
  return out
}

// Actions tab groups. Each is the children of a menu entry, or a fixed list
// of entries, plus entries pulled up from below so they show exactly when
// the menu would show them (Stop Screenrecording lives in Screenrecord).
var ACTION_GROUPS = [
  { key: "capture", menu: "trigger.capture", lead: ["trigger.capture.screenrecord.stop"], color: "cyan" },
  { key: "share", menu: "trigger.share", lead: [], color: "blue" },
  { key: "tools", ids: ["trigger.emoji", "trigger.clipboard-history", "trigger.reminder", "trigger.transcode"], color: "yellow" }
]

function groupIds(group, itemOrder, items) {
  var out = (group.lead || []).slice()
  if (group.ids) return out.concat(group.ids)
  for (var i = 0; i < itemOrder.length; i++) {
    var entry = items[itemOrder[i]]
    if (entry && entry.parent === group.menu && out.indexOf(entry.id) < 0) out.push(entry.id)
  }
  return out
}

// The top-level menu entry a row sits under: "appearance" for
// appearance.theme, so search can group by it.
function topLevelId(items, id) {
  var current = items[id]
  var guard = 0
  while (current && current.parent && current.parent !== "root" && guard < 32) {
    current = items[current.parent]
    guard += 1
  }
  return current ? current.id : ""
}

// How long ago, as [unit, count]: unit is "now", "min", "h" or "d".
function age(then, now) {
  var minutes = Math.floor(Math.max(0, now - then) / 60000)
  if (minutes < 1) return ["now", 0]
  if (minutes < 60) return ["min", minutes]
  var hours = Math.floor(minutes / 60)
  if (hours < 24) return ["h", hours]
  return ["d", Math.floor(hours / 24)]
}
