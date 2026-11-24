echo "The side mute switch mutes the sound while it is on silent"

# labwc's Mute key binding (XF86AudioMute) toggled the mute, and the side
# switch, held down while on silent, repeats it. omarchy-volume mute-key leaves
# the mute to omarchy-mute-switch on a device with the switch and toggles
# elsewhere. An existing ~/.config/labwc/rc.xml gets it where the binding is
# as shipped; labwc reads it at its next start, the next login.
rc="$HOME/.config/labwc/rc.xml"
if [[ -f $rc ]] && grep -q 'command="omarchy-volume mute-toggle"' "$rc"; then
  sed '/<keybind key="XF86AudioMute" allowWhenLocked="yes">/{n;s|<action name="Execute" command="omarchy-volume mute-toggle" />|<action name="Execute" command="omarchy-volume mute-key" />|;}' "$rc" > "$rc.new"
  mv -- "$rc.new" "$rc"
fi
