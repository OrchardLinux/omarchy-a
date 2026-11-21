pragma Singleton
import QtQuick
import Quickshell
import "TimeFormatModel.js" as Model

// 24-hour or 12-hour time, for every clock the shell draws (the bar's, the
// lock screen's, the notification center's, a banner's time). The bar's
// clock format in the shell's config says which: Settings' Date & Time
// switch flips that format's hours (keeping its style), and Appearance's
// Clock picks the style; so the two never disagree.
QtObject {
  id: root

  readonly property string configPath: (Quickshell.env("HOME") || "") + "/.config/omarchy-ipad/shell.json"
  property WatchedFile config: WatchedFile { path: root.configPath }

  // The bar clock's format, "HH:mm" while there is none.
  readonly property string barFormat: clockFormat(config.text)
  readonly property bool use24: is24(barFormat)
  // The time alone, as the clocks show it.
  readonly property string time: use24 ? "HH:mm" : "h:mm AP"

  function clockFormat(text) { return Model.clockFormat(text) }
  function is24(format) { return Model.is24(format) }
  function flipped(format, to24) { return Model.flipped(format, to24) }
}
