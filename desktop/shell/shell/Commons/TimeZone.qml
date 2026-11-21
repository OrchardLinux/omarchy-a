pragma Singleton
import QtQuick

// A time zone change, for the shell's clocks: each only turns at its next
// minute otherwise, and a new zone moves the hour at once. Settings' Date &
// Time calls changed() when it sets one.
QtObject {
  property int revision: 0
  function changed() { revision++ }
}
