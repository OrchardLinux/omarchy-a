echo "The bar gets the control center's button"

# A user's bar layout is theirs (~/.config/omarchy-ipad/shell.json): the
# button goes at the end of its right section, unless it is there already.
config="$HOME/.config/omarchy-ipad/shell.json"
[[ -f $config ]] || exit 0
python3 - "$config" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    config = json.load(f)
right = config.get("bar", {}).get("layout", {}).get("right")
if isinstance(right, list) and not any(isinstance(w, dict) and w.get("id") == "ipadlinux.controlcenter" for w in right):
    # On a phone's narrow bar it waits in the overflow: a finger pulls the
    # control center down there.
    right.append({"id": "ipadlinux.controlcenter", "narrow": False})
    with open(path + ".new", "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    import os
    os.replace(path + ".new", path)
PY
