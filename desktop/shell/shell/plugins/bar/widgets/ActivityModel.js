// The arithmetic of the activity widget, kept Qt-free so it can be unit tested
// under node (tests/test_activity_widget.py). The figures are the ones
// Omactivity's footers show: CPU use is the share of time not spent idle or
// waiting for I/O, memory use is what the kernel does not count as available.

// The first line of /proc/stat, as the time all CPUs spent idle and in all:
//   cpu  user nice system idle iowait irq softirq steal guest guest_nice
// Guest time is already part of user and nice.
function cpuTimes(text) {
  var fields = String(text || "").split("\n", 1)[0].trim().split(/\s+/)
  if (fields[0] !== "cpu" || fields.length < 5) return null
  var total = 0
  for (var i = 1; i <= 8 && i < fields.length; i++) total += Number(fields[i]) || 0
  return { idle: (Number(fields[4]) || 0) + (Number(fields[5]) || 0), total: total }
}

// CPU use between two readings in whole percent, or -1 when there is no
// earlier reading or no time has passed.
function cpuPercent(previous, next) {
  if (!previous || !next) return -1
  var total = next.total - previous.total
  if (!(total > 0)) return -1
  return percent(total - (next.idle - previous.idle), total)
}

// Memory in use from /proc/meminfo in whole percent, or -1 when it cannot be
// told.
function memoryPercent(text) {
  var source = String(text || "")
  function kilobytes(key) {
    var found = new RegExp("^" + key + ":\\s+(\\d+)", "m").exec(source)
    return found ? Number(found[1]) : -1
  }
  var total = kilobytes("MemTotal")
  var available = kilobytes("MemAvailable")
  if (available < 0) {
    var free = kilobytes("MemFree")
    if (free < 0) return -1
    available = free + Math.max(0, kilobytes("Cached")) + Math.max(0, kilobytes("Buffers"))
  }
  if (!(total > 0)) return -1
  return percent(total - available, total)
}

function percent(part, whole) {
  return Math.max(0, Math.min(100, Math.round(100 * part / whole)))
}

// The figure the bar shows: digits padded to three places, so the widget
// keeps its width as the number changes, or bare for a narrow bar.
function label(value, digits, padded) {
  var text = value < 0 ? "--" : String(digits)
  while (padded && text.length < 3) text = " " + text
  return text + "%"
}

if (typeof module !== "undefined") {
  module.exports = {
    cpuTimes: cpuTimes,
    cpuPercent: cpuPercent,
    memoryPercent: memoryPercent,
    label: label
  }
}
