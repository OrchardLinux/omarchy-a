echo "At boot the splash stays until the PIN screen is ready"

# labwc holds the boot splash (startupPicture, labwc's 0012) at boot until the
# lock screen has drawn, instead of a black cover. An existing
# ~/.config/labwc/rc.xml gets it after startupSignal, where it is as shipped;
# labwc reads it at its next start, the next boot.
rc="$HOME/.config/labwc/rc.xml"
if [[ -f $rc ]] && ! grep -q '<startupPicture>' "$rc" && grep -q '<startupSignal>yes</startupSignal>' "$rc"; then
  sed 's|<startupSignal>yes</startupSignal>|<startupSignal>yes</startupSignal>\n    <startupPicture>/usr/share/orchard/splash</startupPicture>|' "$rc" > "$rc.new"
  mv -- "$rc.new" "$rc"
fi
