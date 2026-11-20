echo "Focus shows in the status bar"

# The bar's indicators listed only Stay Awake, so Focus (Do Not Disturb) had
# no icon while on. An existing ~/.config/omarchy-ipad/shell.json gets Dnd
# before Stay Awake, as a new one has it.
config="$HOME/.config/omarchy-ipad/shell.json"
[[ -f $config ]] || exit 0
python3 - "$config" <<'PY'
import json, os, sys
path = sys.argv[1]
with open(path) as f:
    config = json.load(f)
changed = False
layout = config.get("bar", {}).get("layout", {})
for section in layout.values() if isinstance(layout, dict) else []:
    for widget in section if isinstance(section, list) else []:
        if not isinstance(widget, dict) or widget.get("id") != "omarchy.indicators":
            continue
        items = widget.get("items")
        if isinstance(items, list) and "Dnd" not in items:
            at = items.index("StayAwake") if "StayAwake" in items else len(items)
            items.insert(at, "Dnd")
            changed = True
if changed:
    with open(path + ".new", "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.replace(path + ".new", path)
PY
