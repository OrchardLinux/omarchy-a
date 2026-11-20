echo "Notifications appear"

# The notification daemon (omarchy.notifications) was switched off in the
# first tablet build, to get a usable desktop sooner. It is on now; an
# existing ~/.config/omarchy-ipad/shell.json still lists it as disabled.
config="$HOME/.config/omarchy-ipad/shell.json"
[[ -f $config ]] || exit 0
python3 - "$config" <<'PY'
import json, os, sys
path = sys.argv[1]
with open(path) as f:
    config = json.load(f)
disabled = config.get("disabledPlugins")
if isinstance(disabled, list) and "omarchy.notifications" in disabled:
    disabled.remove("omarchy.notifications")
    with open(path + ".new", "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.replace(path + ".new", path)
PY
