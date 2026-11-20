echo "A swipe up from the bottom moves the notification center with the finger"

# labwc leaves the bottom-edge swipe to the notification center and the
# control center (bottomSwipeIgnoreNamespace takes a list since labwc's
# 0009), so it is their own drag rather than the gesture's command.
rc="$HOME/.config/labwc/rc.xml"
if [[ -f $rc ]] && grep -q 'bottomSwipeIgnoreNamespace="wvkbd"' "$rc"; then
  sed 's/bottomSwipeIgnoreNamespace="wvkbd"/bottomSwipeIgnoreNamespace="wvkbd,omarchy-notification-center,omarchy-control-center"/' "$rc" > "$rc.new"
  mv -- "$rc.new" "$rc"
  labwc=${LABWC_PID:-$(pgrep -u "$(id -u)" -x labwc | head -1 || true)}
  [[ -z $labwc ]] || kill -HUP "$labwc"
fi
