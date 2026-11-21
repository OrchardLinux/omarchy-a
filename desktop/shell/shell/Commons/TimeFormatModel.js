// 24-hour or 12-hour time from the bar clock's format (TimeFormat.qml).

function clockFormat(text) {
  try {
    var layout = (JSON.parse(text || "{}").bar || {}).layout || {}
    for (var section in layout) {
      var widgets = layout[section] || []
      for (var i = 0; i < widgets.length; i++)
        if (widgets[i] && widgets[i].id === "omarchy.clock" && widgets[i].format) return String(widgets[i].format)
    }
  } catch (e) {}
  return "HH:mm"
}
// Hours as H (0-23) are 24-hour time; h with AP is 12-hour. Quoted text
// ('W') is not a token. A format without hours reads as 24-hour.
function is24(format) {
  var tokens = String(format).replace(/'[^']*'/g, "")
  return tokens.indexOf("h") < 0 || tokens.indexOf("H") >= 0
}
// The format with its hours the other way: "dddd HH:mm" ↔ "dddd h:mm AP".
function flipped(format, to24) {
  var f = String(format)
  if (to24) return f.replace(/\bh(h?)(:mm(:ss)?)\s*(AP|ap|A|a)/, "HH$2")
  return f.replace(/\bHH?(:mm(:ss)?)/, "h$1 AP")
}

if (typeof module !== "undefined") module.exports = { clockFormat: clockFormat, is24: is24, flipped: flipped }
