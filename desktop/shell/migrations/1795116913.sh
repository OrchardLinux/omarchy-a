echo "A phone's bar: logo and time on the left, status icons on the right"

# On a phone (a narrow bar) the clock joins the logo and every icon stays on
# the bar, with no overflow pages. A user's own layout
# (~/.config/omarchy-ipad/shell.json) changes only where an entry still has
# the setting the package gave it.
config="$HOME/.config/omarchy-ipad/shell.json"
[[ -f $config ]] || exit 0
python3 - "$config" <<'PY'
import json, os, sys
path = sys.argv[1]
with open(path) as f:
    config = json.load(f)
layout = config.get("bar", {}).get("layout", {})
missing = object()
# id: (the package's old setting, the new one); missing = no setting.
changes = {
    "omarchy.clock": (missing, "left"),
    "omarchy.indicators": ("left", missing),
    "omarchy.audio": (False, missing),
    "omarchy.bluetooth": (False, missing),
    "omarchy.network": ("left", missing),
    "omarchy.monitor": (False, missing),
    "ipadlinux.controlcenter": (False, missing),
}
changed = False
for section in layout.values():
    if not isinstance(section, list):
        continue
    for entry in section:
        if not isinstance(entry, dict) or entry.get("id") not in changes:
            continue
        old, new = changes[entry["id"]]
        if entry.get("narrow", missing) is not old and entry.get("narrow", missing) != old:
            continue
        if new is missing:
            entry.pop("narrow", None)
        else:
            entry["narrow"] = new
        changed = True
if changed:
    with open(path + ".new", "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.replace(path + ".new", path)
PY
