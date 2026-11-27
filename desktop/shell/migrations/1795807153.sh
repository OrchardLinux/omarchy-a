echo "A swipe up from the bottom opens the overview, and on past half the screen the launcher"

# labwc's 0013: the bottom-edge swipe drives the overview with the finger,
# and swiped on past half the screen opens the launcher. It used to open
# the keyboard, which now opens on its own for a text field.
rc="$HOME/.config/labwc/rc.xml"
if [[ -f $rc ]] && grep -q 'bottomSwipeCommand="omarchy-bottom-swipe"' "$rc" && ! grep -q 'bottomSwipeOverview=' "$rc"; then
  awk '{ print } /bottomSwipeCommand="omarchy-bottom-swipe"/ {
    print "    bottomSwipeOverview=\"yes\""
    print "    bottomSwipeFarCommand=\"omarchy-shell omarchy.dock openApps\""
  }' "$rc" > "$rc.new"
  mv -- "$rc.new" "$rc"
  labwc=${LABWC_PID:-$(pgrep -u "$(id -u)" -x labwc | head -1 || true)}
  [[ -z $labwc ]] || kill -HUP "$labwc"
fi
