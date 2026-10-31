#!/bin/sh
# Earlier instructions ran this file from main. The installer ships with each
# release now; this runs the latest release's install.sh.
set -eu
script=$(mktemp)
trap 'rm -f "$script"' EXIT INT TERM
curl -fsSL --retry 3 --proto '=https' --tlsv1.2 -o "$script" \
    https://github.com/OrchardLinux/omarchy-a/releases/latest/download/install.sh
sh "$script" "$@"
