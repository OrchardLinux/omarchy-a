import QtQuick
import Quickshell

// Copy beside ScreenMoveRemap.qml and run with qs. No windows are created.
Scope {
  id: test
  property int pulses: 0
  property bool failed: false
  QtObject { id: fakeScreen; property real x: 0; property real y: 0; property real width: 768; property real height: 1024 }
  QtObject { id: fakeWindow; property var screen: fakeScreen }
  ScreenMoveRemap {
    id: guard
    window: fakeWindow
    onRemappingChanged: if (remapping) test.pulses++
  }
  function check(condition, message) {
    if (!condition) { test.failed = true; console.error("FAIL: " + message) }
  }
  Timer {
    interval: 50; running: true
    onTriggered: {
      fakeScreen.width = 1024; fakeScreen.height = 768
      fakeScreen.xChanged(); fakeScreen.yChanged()
      rotationCheck.start()
    }
  }
  Timer {
    id: rotationCheck; interval: 300
    onTriggered: {
      test.check(test.pulses === 0 && !guard.remapping, "rotation notifications at (0,0) must not remap")
      fakeScreen.x = 100
      fakeScreen.yChanged() // redundant notification must not add a pulse
      movementCheck.start()
    }
  }
  Timer {
    id: movementCheck; interval: 300
    onTriggered: {
      test.check(test.pulses === 1 && !guard.remapping, "actual origin movement must remap exactly once")
      console.log(test.failed ? "SCREEN_REMAP_FAIL" : "SCREEN_REMAP_PASS")
      Qt.quit()
    }
  }
}
