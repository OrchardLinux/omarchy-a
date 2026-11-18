echo "The on-screen keyboard opens when a text field is tapped"

# Labwc reports text fields, taps and physical typing to omarchy-keyboard,
# which decides when the keyboard opens. A new user's rc.xml has the line;
# an existing one gets it beside the overview's.
rc="$HOME/.config/labwc/rc.xml"
if [[ -f $rc ]] && ! grep -q '<onScreenKeyboard' "$rc" && grep -q '^  <keyboard>' "$rc"; then
  sed '0,/^  <keyboard>/s##  <onScreenKeyboard listener="omarchy-keyboard listen" />\n  <keyboard>#' "$rc" > "$rc.new"
  mv -- "$rc.new" "$rc"
fi
