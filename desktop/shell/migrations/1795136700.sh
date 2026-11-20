echo "A swipe up from the bottom puts the notification center away"

# labwc's bottom-edge swipe ran omarchy-keyboard show; omarchy-bottom-swipe
# puts the notification center or the control center away first, else
# opens the keyboard as before.
rc="$HOME/.config/labwc/rc.xml"
if [[ -f $rc ]] && grep -q 'bottomSwipeCommand="omarchy-keyboard show"' "$rc"; then
  sed 's/bottomSwipeCommand="omarchy-keyboard show"/bottomSwipeCommand="omarchy-bottom-swipe"/' "$rc" > "$rc.new"
  mv -- "$rc.new" "$rc"
  labwc=${LABWC_PID:-$(pgrep -u "$(id -u)" -x labwc | head -1 || true)}
  [[ -z $labwc ]] || kill -HUP "$labwc"
fi
