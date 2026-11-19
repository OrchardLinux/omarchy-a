echo "Home's action comes from the button itself"

# omarchy-powerd now runs omarchy-home-button when Home is let go, so
# labwc's Home binding only keeps the key from the focused app. An existing
# rc.xml still runs the script from labwc as well (two runs would read as a
# double press and open the overview).
rc="$HOME/.config/labwc/rc.xml"
if [[ -f $rc ]] && grep -q '<keybind key="XF86HomePage" onRelease="yes">' "$rc"; then
  python3 - "$rc" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
old = '''    <keybind key="XF86HomePage" onRelease="yes">
      <action name="Execute" command="omarchy-home-button" />
    </keybind>'''
new = '''    <keybind key="XF86HomePage">
      <action name="Execute" command="/usr/bin/true" />
    </keybind>'''
if old in text:
    open(path + '.new', 'w').write(text.replace(old, new, 1))
    import os
    os.replace(path + '.new', path)
PY
  labwc=${LABWC_PID:-$(pgrep -u "$(id -u)" -x labwc | head -1 || true)}
  [[ -z $labwc ]] || kill -HUP "$labwc"
fi
