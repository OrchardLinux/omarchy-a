echo "The bar's right side: Stay Awake joins it, the keyboard button leaves"

# The swipe up from the bottom and the control center's Keyboard toggle bring
# the keyboard up; Stay Awake's indicator sits with the status icons. A user's
# own layout (~/.config/omarchy-ipad/shell.json) changes only where it still
# has these as the package placed them.
config="$HOME/.config/omarchy-ipad/shell.json"
[[ -f $config ]] || exit 0
python3 - "$config" <<'PY'
import json, os, sys
path = sys.argv[1]
with open(path) as f:
    config = json.load(f)
layout = config.get("bar", {}).get("layout", {})
right = layout.get("right")
if not isinstance(right, list):
    sys.exit(0)
changed = False
kept = [w for w in right if not (isinstance(w, dict) and w.get("id") == "ipadlinux.keyboard")]
if len(kept) != len(right):
    right[:] = kept
    changed = True
begin = layout.get("centerBegin")
if isinstance(begin, list):
    for widget in list(begin):
        if isinstance(widget, dict) and widget.get("id") == "omarchy.indicators" and widget.get("items") == ["StayAwake"]:
            begin.remove(widget)
            if not any(isinstance(w, dict) and w.get("id") == "omarchy.indicators" for w in right):
                right.insert(0, dict(widget, narrow="left"))
            changed = True
if changed:
    with open(path + ".new", "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.replace(path + ".new", path)
PY
