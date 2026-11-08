import QtQuick

// Labwc repositions mapped layer-shell surfaces itself when outputs move or
// resize. Qt emits x/y notifications for a size-only change too. The old
// Hyprland workaround hid every panel and wallpaper 200ms later, destroying
// their layer surfaces and buffers for at least another 50ms. On a software
// renderer recreation/decoding extends that gap. Keep the public component
// interface, but never unmap a labwc layer just because its output changed.
Item {
  required property var window
  readonly property bool remapping: false
  visible: false
}
