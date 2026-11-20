echo "Super+Ctrl+2 opens the notification center"

# A new user's rc.xml has the binding; an existing one gets it before the
# launcher's (Super+Space), unless the key is bound already.
rc="$HOME/.config/labwc/rc.xml"
if [[ -f $rc ]] && ! grep -q 'key="W-C-2"' "$rc" && grep -q '^    <keybind key="W-space">' "$rc"; then
  sed '0,/^    <keybind key="W-space">/s##    <keybind key="W-C-2">\n      <action name="Execute" command="omarchy-shell omarchy.notificationcenter toggle" />\n    </keybind>\n    <keybind key="W-space">#' "$rc" > "$rc.new"
  mv -- "$rc.new" "$rc"
  labwc=${LABWC_PID:-$(pgrep -u "$(id -u)" -x labwc | head -1 || true)}
  [[ -z $labwc ]] || kill -HUP "$labwc"
fi
