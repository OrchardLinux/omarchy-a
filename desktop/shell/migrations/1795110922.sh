echo "Super+Ctrl+A, B, D, N and P open Audio, Bluetooth, Display, Network and Power"

# Upstream's module keys. A new user's rc.xml has them; an existing one gets
# each one it lacks before the launcher's (Super+Space).
rc="$HOME/.config/labwc/rc.xml"
[[ -f $rc ]] && grep -q '^    <keybind key="W-space">' "$rc" || exit 0
for pair in a:omarchy.audio b:omarchy.bluetooth d:omarchy.monitor n:omarchy.network p:omarchy.power; do
  key=${pair%%:*} module=${pair#*:}
  grep -q "key=\"W-C-$key\"" "$rc" && continue
  sed "0,/^    <keybind key=\"W-space\">/s##    <keybind key=\"W-C-$key\">\n      <action name=\"Execute\" command=\"omarchy-shell shell toggle $module\" />\n    </keybind>\n    <keybind key=\"W-space\">#" "$rc" > "$rc.new"
  mv -- "$rc.new" "$rc"
done
