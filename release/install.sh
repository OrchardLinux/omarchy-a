#!/bin/sh
# Install Omarchy A on an iPad or iPhone in DFU mode:
#   curl -fsSL @URL@ | sh
# It installs the orchard command (OrchardLinux/tools) or brings it up to
# date, then runs `orchard install` for this release. Arguments go to
# `orchard install`: sh -s -- --ibss, for example.
set -eu
INDEX=@INDEX@
# Next to a local build, its own index.
case "$0" in
    install.sh|*/install.sh)
        here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
        [ ! -f "$here/index.toml" ] || INDEX="$here/index.toml" ;;
esac
command -v curl >/dev/null 2>&1 || { echo 'curl is needed to download the orchard command.' >&2; exit 1; }
curl -fsSL https://raw.githubusercontent.com/OrchardLinux/tools/main/install.sh | sh
orchard=${ORCHARD_BIN:-$HOME/.local/bin}/orchard
# The installer asks on the terminal, also when this script came through a pipe.
if [ -t 0 ] || ! (: </dev/tty) 2>/dev/null; then
    exec "$orchard" install "$INDEX" "$@"
fi
exec "$orchard" install "$INDEX" "$@" </dev/tty
