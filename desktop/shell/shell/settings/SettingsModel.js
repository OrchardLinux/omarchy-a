// The Settings window's rows, worked out from the layout (SettingsLayout.js)
// and the Omarchy menu's live state: what each row shows, whether it is a
// switch, a list to pick from, a page or an action, and whether it can work
// here. Plain functions over plain data, so they run under node in tests.
//
// `ctx` is the menu's state as the menu plugin keeps it:
//   { items, itemOrder, whenResults, checkedResults, disabledResults,
//     values: { rowKey: "current value" },
//     missing: { "omarchy-command": true } }   commands not installed

function item(ctx, id) {
  return ctx && ctx.items && Object.prototype.hasOwnProperty.call(ctx.items, id) ? ctx.items[id] : null
}

// `when` hides on an explicit false only, as the menu does: an entry whose
// guard has not been answered yet shows.
function whenAllows(ctx, entry) {
  if (!entry) return false
  if (!entry.when) return true
  return !(ctx.whenResults && ctx.whenResults[entry.id] === false)
}

function childrenOf(ctx, id) {
  var out = []
  var order = ctx && Array.isArray(ctx.itemOrder) ? ctx.itemOrder : []
  for (var i = 0; i < order.length; i++) {
    var child = item(ctx, order[i])
    if (child && child.parent === id) out.push(child)
  }
  return out
}

// An entry is shown where its own `when` and every section above it allow.
function shown(ctx, entry) {
  var current = entry
  for (var guard = 0; current && current.id !== "root" && guard < 32; guard++) {
    if (!whenAllows(ctx, current)) return false
    current = item(ctx, current.parent)
  }
  return !!entry
}

// The commands an action or a script calls by name: the ones it needs
// installed. Only Omarchy's own commands are checked; anything else is part
// of the system.
function commandsIn(text) {
  var found = {}
  var re = /(^|[^A-Za-z0-9_.\/-])(omarchy-[a-z0-9][a-z0-9-]*)/g
  var m
  var source = String(text || "")
  while ((m = re.exec(source)) !== null) found[m[2]] = true
  return Object.keys(found).sort()
}

function missingIn(ctx, text) {
  var commands = commandsIn(text)
  var out = []
  for (var i = 0; i < commands.length; i++) if (ctx.missing && ctx.missing[commands[i]]) out.push(commands[i])
  return out
}

// "Hyprland" for an entry that only does something under Hyprland: its
// commands are Hyprland's (omarchy-hyprland-*, hyprctl) and not here.
function tagFor(missing, text) {
  var source = String(text || "")
  for (var i = 0; i < missing.length; i++) if (missing[i].indexOf("hyprland") >= 0) return "Hyprland"
  if (missing.length > 0 && /\bhyprctl\b/.test(source)) return "Hyprland"
  return ""
}

// Everything an entry runs: its action, a provider's script, and for a
// submenu everything below it.
function entryText(ctx, entry, providers, depth) {
  if (!entry) return ""
  var text = String(entry.action || "")
  if (entry.provider && providers && providers[entry.provider]) text += "\n" + String(providers[entry.provider].script || "")
  if (entry.kind === "menu" && !entry.provider && (depth || 0) < 4) {
    var kids = childrenOf(ctx, entry.id)
    for (var i = 0; i < kids.length; i++) text += "\n" + entryText(ctx, kids[i], providers, (depth || 0) + 1)
  }
  return text
}

// A submenu whose children say which one is current (`checked`) is a list
// to pick one from; its value is the current child.
function isChoice(ctx, entry) {
  if (!entry || entry.kind !== "menu") return false
  if (entry.provider) return true
  var kids = childrenOf(ctx, entry.id)
  for (var i = 0; i < kids.length; i++) if (kids[i].checked) return true
  return false
}

function checkedChild(ctx, entry) {
  var kids = childrenOf(ctx, entry.id)
  for (var i = 0; i < kids.length; i++) {
    var kid = kids[i]
    if (!shown(ctx, kid)) continue
    if (kid.checked && ctx.checkedResults && ctx.checkedResults[kid.id]) return kid
    // A provider's rows mark the current one with ✓ in place of the icon.
    if (entry.provider && kid.icon === "✓") return kid
  }
  return null
}

// A menu pair, X On and X Off (or Show X and Hide X), as the menu offers it:
// each shown only while it would change something. Its label without the
// On/Off word.
var PAIR_SUFFIXES = [["-on", "-off"], ["-show", "-hide"]]

function pairLabel(label) {
  return String(label || "").replace(/\s+(On|Off)$/, "")
}

function rowKey(spec, index) {
  if (spec.entry) return spec.entry
  if (spec.toggle) return "toggle:" + spec.toggle[0]
  if (spec.page) return "page:" + spec.page
  return "row:" + (index || 0)
}

// One row: what it shows and does, or null when it does not apply here
// (its `when` says no).
//   kind: "switch" | "choice" | "page" | "native" | "action"
function resolveRow(spec, ctx, providers, t) {
  var tr = t || function(key) { return key }
  var key = rowKey(spec)
  var values = ctx.values || {}

  if (spec.toggle) {
    var onEntry = item(ctx, spec.toggle[0])
    var offEntry = item(ctx, spec.toggle[1])
    if (!onEntry && !offEntry) return null
    var onShown = onEntry && shown(ctx, onEntry)
    var offShown = offEntry && shown(ctx, offEntry)
    if (!onShown && !offShown) return null
    var text = (onEntry ? onEntry.action : "") + "\n" + (offEntry ? offEntry.action : "")
    var missing = missingIn(ctx, text)
    return {
      key: key, kind: "switch",
      label: spec.label ? tr(spec.label) : pairLabel(onEntry ? onEntry.label : offEntry.label),
      icon: (onEntry || offEntry).icon || "",
      on: !!offShown,
      // Flipping runs whichever of the two is shown now.
      entry: offShown ? offEntry : onEntry,
      value: "",
      available: missing.length === 0,
      tag: tagFor(missing, text)
    }
  }

  if (spec.page && !spec.entry) {
    return { key: key, kind: "native", page: spec.page, label: spec.label ? tr(spec.label) : spec.page,
             icon: spec.icon || "", value: values[key] || "", available: true, tag: "" }
  }

  var entry = item(ctx, spec.entry)
  if (!entry || !shown(ctx, entry)) return null
  var all = entryText(ctx, entry, providers)
  var gone = missingIn(ctx, all)
  // A submenu works as long as something in it does.
  var available = gone.length === 0 || (entry.kind === "menu" && !entry.provider && submenuWorks(ctx, entry, providers))
  var row = {
    key: key, entry: entry, label: entry.label, icon: entry.icon || "", iconFont: entry.iconFont || "",
    value: values[key] || "", available: available, tag: available ? "" : tagFor(gone, all),
    off: !!(entry.disabled && ctx.disabledResults && ctx.disabledResults[entry.id])
  }
  if (spec.page) { row.kind = "native"; row.page = spec.page; return row }
  if (isChoice(ctx, entry)) {
    row.kind = "choice"
    var current = checkedChild(ctx, entry)
    if (!row.value && current) row.value = current.label
    return row
  }
  if (entry.kind === "menu" || entry.kind === "link") { row.kind = "page"; return row }
  row.kind = "action"
  return row
}

function submenuWorks(ctx, entry, providers) {
  var kids = childrenOf(ctx, entry.id)
  for (var i = 0; i < kids.length; i++) {
    if (!shown(ctx, kids[i])) continue
    if (missingIn(ctx, entryText(ctx, kids[i], providers)).length === 0) return true
  }
  return false
}

// A menu's children as layout rows: an X On / X Off pair becomes one switch,
// everything else stays the entry it is.
function menuSpecs(ctx, menuId) {
  var kids = childrenOf(ctx, menuId)
  var byId = {}
  for (var i = 0; i < kids.length; i++) byId[kids[i].id] = kids[i]
  var used = {}
  var specs = []
  for (var j = 0; j < kids.length; j++) {
    var kid = kids[j]
    if (used[kid.id]) continue
    var paired = false
    for (var s = 0; s < PAIR_SUFFIXES.length && !paired; s++) {
      var on = PAIR_SUFFIXES[s][0], off = PAIR_SUFFIXES[s][1]
      var stem = null, other = null, first = null
      if (kid.id.slice(-on.length) === on) { stem = kid.id.slice(0, -on.length); other = stem + off; first = "on" }
      else if (kid.id.slice(-off.length) === off) { stem = kid.id.slice(0, -off.length); other = stem + on; first = "off" }
      if (stem !== null && byId[other] && kid.action && byId[other].action) {
        var onId = first === "on" ? kid.id : other
        var offId = first === "on" ? other : kid.id
        specs.push({ toggle: [onId, offId] })
        used[onId] = used[offId] = true
        paired = true
      }
    }
    if (!paired) specs.push({ entry: kid.id })
  }
  return specs
}

function resolveRows(specs, ctx, providers, t) {
  var out = []
  for (var i = 0; i < specs.length; i++) {
    var row = resolveRow(specs[i], ctx, providers, t)
    if (row) out.push(row)
  }
  return out
}

// A choice's options: the children, the current one marked.
function choiceRows(ctx, entry) {
  var out = []
  if (!entry) return out
  var current = checkedChild(ctx, entry)
  var kids = childrenOf(ctx, entry.id)
  for (var i = 0; i < kids.length; i++) {
    var kid = kids[i]
    if (!shown(ctx, kid)) continue
    out.push({
      key: kid.id, kind: kid.kind === "action" ? "option" : "page", entry: kid,
      label: kid.label, icon: kid.icon === "✓" ? "" : (kid.icon || ""),
      current: current ? current.id === kid.id : false,
      available: missingIn(ctx, kid.action).length === 0, tag: "",
      off: !!(kid.disabled && ctx.disabledResults && ctx.disabledResults[kid.id])
    })
  }
  return out
}

// The groups of a section, resolved, without the empty ones.
function sectionGroups(section, ctx, providers, t) {
  var out = []
  if (!section) return out
  for (var g = 0; g < section.groups.length; g++) {
    var group = section.groups[g]
    var rows = resolveRows(group.rows, ctx, providers, t)
    if (rows.length === 0) continue
    out.push({ label: group.label ? (t ? t(group.label) : group.label) : "", card: !!group.card, rows: rows })
  }
  return out
}

// Which section a menu entry is placed in, through itself or a menu above it.
function sectionFor(sections, ctx, id) {
  var current = item(ctx, id)
  var target = id
  for (var guard = 0; target && guard < 32; guard++) {
    for (var s = 0; s < sections.length; s++) {
      var groups = sections[s].groups
      for (var g = 0; g < groups.length; g++) {
        var rows = groups[g].rows
        for (var r = 0; r < rows.length; r++) {
          var spec = rows[r]
          if (spec.entry === target || (spec.toggle && spec.toggle.indexOf(target) >= 0)) return sections[s].id
        }
      }
    }
    current = item(ctx, target)
    target = current ? current.parent : ""
  }
  // A menu the layout only places piece by piece (Setup › Security): the
  // section its first placed child is in.
  var kids = childrenOf(ctx, id)
  for (var k = 0; k < kids.length; k++) {
    var home = sectionForPlaced(sections, kids[k].id)
    if (home) return home
  }
  return ""
}

function sectionForPlaced(sections, id) {
  for (var s = 0; s < sections.length; s++)
    for (var g = 0; g < sections[s].groups.length; g++)
      for (var r = 0; r < sections[s].groups[g].rows.length; r++) {
        var spec = sections[s].groups[g].rows[r]
        if (spec.entry === id || (spec.toggle && spec.toggle.indexOf(id) >= 0)) return sections[s].id
      }
  return ""
}

// Every menu id the layout places, directly or as a pair.
function placedIds(sections) {
  var ids = {}
  for (var s = 0; s < sections.length; s++)
    for (var g = 0; g < sections[s].groups.length; g++)
      for (var r = 0; r < sections[s].groups[g].rows.length; r++) {
        var spec = sections[s].groups[g].rows[r]
        if (spec.entry) ids[spec.entry] = true
        if (spec.toggle) { ids[spec.toggle[0]] = true; ids[spec.toggle[1]] = true }
      }
  return ids
}

// Menu entries with no place in Settings, below none that has one: what an
// upstream update added, for a person to give a home (or name as living
// elsewhere).
function unplaced(sections, elsewhere, items, itemOrder) {
  var ctx = { items: items, itemOrder: itemOrder }
  var placed = placedIds(sections)
  var away = {}
  for (var i = 0; i < elsewhere.length; i++) away[elsewhere[i]] = true
  var out = []
  for (var j = 0; j < itemOrder.length; j++) {
    var id = itemOrder[j]
    if (id === "root" || placed[id] || away[id]) continue
    var parent = item(ctx, id) ? item(ctx, id).parent : ""
    var covered = false
    for (var guard = 0; parent && parent !== "root" && guard < 32; guard++) {
      // Below a placed entry, the entry's page holds it; below an entry
      // that lives elsewhere, it lives there too, unless that is only one
      // of the menu's own sections.
      if (placed[parent]) { covered = true; break }
      if (away[parent] && !isSectionOnly(parent)) { covered = true; break }
      parent = item(ctx, parent) ? item(ctx, parent).parent : ""
    }
    if (!covered) out.push(id)
  }
  return out
}

// The menu's sections that only group what is placed one by one.
var SECTION_ONLY = {
  "trigger": true, "system": true, "setup": true, "appearance": true, "update": true, "update.password": true,
  "setup.default": true, "setup.keyboard": true, "setup.security": true, "setup.network": true,
  "appearance.top-bar": true, "appearance.top-bar.indicators": true, "appearance.windows": true,
  "appearance.branding": true, "trigger.toggle": true, "trigger.hardware": true, "trigger.tests": true
}
function isSectionOnly(id) { return !!SECTION_ONLY[id] }

// Search: the rows the layout places, then every other menu entry, best
// match first. Each result knows the section it opens in.
function search(query, sections, ctx, providers, t, scoreOf) {
  var q = String(query || "").trim().toLowerCase()
  if (!q) return []
  var out = []
  var seen = {}
  for (var s = 0; s < sections.length; s++) {
    var section = sections[s]
    var sectionLabel = t ? t(section.label) : section.label
    for (var g = 0; g < section.groups.length; g++) {
      var rows = section.groups[g].rows
      for (var r = 0; r < rows.length; r++) {
        var row = resolveRow(rows[r], ctx, providers, t)
        if (!row) continue
        var score = textScore(q, row.label, row.entry)
        if (score < 0) continue
        seen[row.key] = true
        if (rows[r].toggle) { seen[rows[r].toggle[0]] = true; seen[rows[r].toggle[1]] = true }
        row.section = section.id
        row.path = sectionLabel
        row.score = score + 100
        out.push(row)
      }
    }
  }
  var order = Array.isArray(ctx.itemOrder) ? ctx.itemOrder : []
  for (var i = 0; i < order.length; i++) {
    var id = order[i]
    if (seen[id] || id === "root") continue
    var entry = item(ctx, id)
    if (!entry || !shown(ctx, entry)) continue
    var sc = scoreOf ? scoreOf(entry, q) : textScore(q, entry.label, entry)
    if (sc < 0) continue
    var resolved = resolveRow({ entry: id }, ctx, providers, t)
    if (!resolved) continue
    resolved.section = sectionFor(sections, ctx, id)
    resolved.path = pathLabel(ctx, entry)
    resolved.score = sc
    out.push(resolved)
  }
  out.sort(function(a, b) { return b.score - a.score || a.label.localeCompare(b.label) })
  return out
}

function textScore(q, label, entry) {
  var l = String(label || "").toLowerCase()
  if (l === q) return 60
  if (l.indexOf(q) === 0) return 50
  if (l.indexOf(" " + q) >= 0) return 40
  if (l.indexOf(q) >= 0) return 30
  var aliases = entry && entry.aliases ? entry.aliases : []
  for (var i = 0; i < aliases.length; i++) if (String(aliases[i]).toLowerCase().indexOf(q) === 0) return 20
  return -1
}

// "Setup › Security" for an entry: the menus above it.
function pathLabel(ctx, entry) {
  var parts = []
  var current = entry ? item(ctx, entry.parent) : null
  for (var guard = 0; current && current.id !== "root" && guard < 32; guard++) {
    parts.unshift(current.label)
    current = item(ctx, current.parent)
  }
  return parts.join(" › ")
}

// The commands a set of rows needs and the values they show, as one bash
// script: one line per answer, "m\t<command>" for a command not installed,
// "v\t<row key>\t<value>" for a value.
function stateScript(sections, ctx, providers) {
  var commands = {}
  var lines = []
  var order = Array.isArray(ctx.itemOrder) ? ctx.itemOrder : []
  for (var i = 0; i < order.length; i++) {
    var entry = item(ctx, order[i])
    if (!entry) continue
    var names = commandsIn(entry.action)
    if (entry.provider && providers && providers[entry.provider]) names = names.concat(commandsIn(providers[entry.provider].script))
    for (var n = 0; n < names.length; n++) commands[names[n]] = true
  }
  var list = Object.keys(commands).sort()
  if (list.length) lines.push("for c in " + list.join(" ") + "; do command -v \"$c\" >/dev/null 2>&1 || printf 'm\\t%s\\n' \"$c\"; done")
  for (var s = 0; s < sections.length; s++)
    for (var g = 0; g < sections[s].groups.length; g++)
      for (var r = 0; r < sections[s].groups[g].rows.length; r++) {
        var spec = sections[s].groups[g].rows[r]
        if (!spec.value) continue
        lines.push("v=$( { " + spec.value + " ; } 2>/dev/null | head -n1 ); [[ -n $v ]] && printf 'v\\t%s\\t%s\\n' " + shellQuote(rowKey(spec)) + " \"$v\"")
      }
  return lines.join("\n")
}

function parseState(text) {
  var missing = {}
  var values = {}
  var lines = String(text || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var parts = lines[i].split("\t")
    if (parts[0] === "m" && parts[1]) missing[parts[1]] = true
    else if (parts[0] === "v" && parts[1]) values[parts[1]] = parts.slice(2).join("\t")
  }
  return { missing: missing, values: values }
}

function shellQuote(value) {
  return "'" + String(value).replace(/'/g, "'\\''") + "'"
}

// A deep link: "appearance", "appearance/theme", or a menu id
// ("setup.security"), into the section that places it and the page to open.
function route(path, sections, ctx) {
  var text = String(path || "").trim()
  if (!text) return { section: "", page: null }
  var parts = text.split("/")
  for (var s = 0; s < sections.length; s++) {
    if (sections[s].id !== parts[0]) continue
    var page = parts.length > 1 ? nativeOrEntry(parts.slice(1).join("/"), ctx) : null
    return { section: sections[s].id, page: page }
  }
  var native = { theme: "appearance", background: "appearance", icons: "appearance" }
  if (native[text]) return { section: native[text], page: { kind: "native", page: text } }
  var entry = item(ctx, text)
  if (entry) {
    var home = sectionFor(sections, ctx, text)
    if (entry.kind === "menu") return { section: home, page: { kind: isChoice(ctx, entry) ? "choice" : "menu", id: text } }
    return { section: home, page: null }
  }
  return { section: "", page: null }
}

function nativeOrEntry(rest, ctx) {
  if (rest === "theme" || rest === "background" || rest === "icons") return { kind: "native", page: rest }
  var entry = item(ctx, rest)
  if (entry && entry.kind === "menu") return { kind: isChoice(ctx, entry) ? "choice" : "menu", id: rest }
  return null
}

// A theme's colors.toml as { key: "#rrggbb" }: the lines the theme picker
// draws a theme from.
function parseColors(text) {
  var out = {}
  var lines = String(text || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var m = /^\s*([a-z_]+)\s*=\s*"(#[0-9a-fA-F]{6,8})"/.exec(lines[i])
    if (m) out[m[1]] = m[2]
  }
  return out
}

// "tokyo-night" → "Tokyo Night", as omarchy-theme-current names it.
function displayName(slug) {
  return String(slug || "").split("-").map(function(w) { return w ? w.charAt(0).toUpperCase() + w.slice(1) : w }).join(" ")
}

// The five colours a theme is shown by, from its colors.toml.
function swatchesOf(colors) {
  var keys = ["accent", "red", "green", "yellow", "magenta"]
  var out = []
  for (var i = 0; i < keys.length; i++) if (colors[keys[i]]) out.push(colors[keys[i]])
  return out
}

if (typeof module !== "undefined") module.exports = {
  parseColors: parseColors, displayName: displayName, swatchesOf: swatchesOf,
  commandsIn: commandsIn, resolveRow: resolveRow, resolveRows: resolveRows, menuSpecs: menuSpecs,
  choiceRows: choiceRows, sectionGroups: sectionGroups, sectionFor: sectionFor, unplaced: unplaced,
  search: search, stateScript: stateScript, parseState: parseState, route: route, pairLabel: pairLabel,
  childrenOf: childrenOf, shown: shown, isChoice: isChoice
}
