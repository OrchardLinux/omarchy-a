function clampIndex(index, length) {
  if (length <= 0) return 0
  return Math.max(0, Math.min(length - 1, index))
}

function selectProfileIndex(index, delta, profiles) {
  var values = Array.isArray(profiles) ? profiles : []
  if (values.length === 0) return 0
  return clampIndex(index + delta, values.length)
}

function parseKeyValue(raw) {
  var next = {}
  var lines = String(raw || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var idx = lines[i].indexOf("\t")
    if (idx <= 0) continue
    next[lines[i].substring(0, idx)] = lines[i].substring(idx + 1).trim()
  }
  return next
}

function parseProfiles(raw, previousIndex) {
  var lines = String(raw || "").split("\n")
  var list = []
  var active = ""
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim()
    if (!line) continue
    var parts = line.split("\t")
    list.push(parts[0])
    if (parts[1] === "1") active = parts[0]
  }
  return {
    profiles: list,
    activeProfile: active,
    profileIndex: clampIndex(previousIndex || 0, list.length)
  }
}

function profileIcon(name) {
  if (name === "power-saver") return "󰌪"
  if (name === "balanced") return "󰊚"
  if (name === "performance") return "󰓅"
  return "󰂄"
}

function batteryPercentage(device, info) {
  // A measured sysfs snapshot is available before UPower finishes discovery.
  var match = /^(\d{1,3})%$/.exec(String(info && info.percentage || ""))
  if (match && Number(match[1]) <= 100) return Number(match[1])
  if (device && device.isPresent && typeof device.percentage === "number"
      && isFinite(device.percentage) && device.percentage >= 0 && device.percentage <= 1)
    return Math.round(device.percentage * 100)
  return null
}

function batteryFraction(device, info) {
  var value = batteryPercentage(device, info)
  return value === null ? 0 : value / 100
}

function chargeThresholdActive(device, onBattery, states) {
  // The iPad's conservative charging guard is not a user-configured battery
  // threshold. Neither PendingCharge nor low net current proves one exists.
  return !!(device && device.isPresent && device.chargeThresholdActive === true)
}

function batteryIcon(device, onBattery, states, externalPower) {
  var d = device || {}
  if (!d.isPresent) return ""

  var chargingIcons = ["󰢜", "󰂆", "󰂇", "󰂈", "󰢝", "󰂉", "󰢞", "󰂊", "󰂋", "󰂅"]
  var defaultIcons = ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]
  var index = Math.max(0, Math.min(9, Math.floor(d.percentage * 10)))
  if (d.state === states.FullyCharged) return externalPower === false ? defaultIcons[9] : "󰂅"
  if (externalPower === true || (externalPower !== false && d.state === states.Charging)) return chargingIcons[index]
  return defaultIcons[index]
}

function modeLabel(device, onBattery, states, tr) {
  var t = typeof tr === "function" ? tr : function(key, english) { return english }
  var d = device || {}
  if (!d.isPresent) return ""

  if (chargeThresholdActive(d, onBattery, states)) return t("power.threshold", "Threshold")
  // UPower.onBattery describes power-source policy, not the pack's net flow.
  // A plugged-in iPad may discharge under a guarded 425mA limit.
  if (d.state === states.FullyCharged) return t("power.fullyCharged", "Fully charged")
  if (d.state === states.Charging) return t("power.charging", "Charging")
  if (d.state === states.Discharging) return t("power.discharging", "Discharging")
  if (d.state === states.PendingCharge) return t("power.notCharging", "Not charging")
  return t("power.stateUnavailable", "Battery state unavailable")
}

// omarchy-battery-status --shell answers in plain digits with the unit
// attached ("13.1W", "75-80%"); the panel writes each number in the
// language's digits and decimal separator, keeping its decimals and unit.
function localizeReading(raw, fmt) {
  var f = typeof fmt === "function" ? fmt : function(v, d) { return d === undefined ? String(v) : Number(v).toFixed(d) }
  return String(raw === undefined || raw === null ? "" : raw).replace(/\d+(?:\.\d+)?/g, function(number) {
    var dot = number.indexOf(".")
    return f(Number(number), dot < 0 ? undefined : number.length - dot - 1)
  })
}

function profileLabel(name, tr) {
  var t = typeof tr === "function" ? tr : function(key, english) { return english }
  var value = String(name || "")
  if (value === "power-saver") return t("power.profilePowerSaver", "Power-saver")
  if (value === "balanced") return t("power.profileBalanced", "Balanced")
  if (value === "performance") return t("power.profilePerformance", "Performance")
  return value.charAt(0).toUpperCase() + value.slice(1)
}

if (typeof module !== "undefined") {
  module.exports = {
    clampIndex: clampIndex,
    selectProfileIndex: selectProfileIndex,
    parseKeyValue: parseKeyValue,
    parseProfiles: parseProfiles,
    profileIcon: profileIcon,
    batteryPercentage: batteryPercentage,
    batteryFraction: batteryFraction,
    chargeThresholdActive: chargeThresholdActive,
    batteryIcon: batteryIcon,
    modeLabel: modeLabel,
    profileLabel: profileLabel,
    localizeReading: localizeReading
  }
}
