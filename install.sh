#!/usr/bin/env bash
set -euo pipefail

command -v python3 >/dev/null || { echo 'Install Python 3.9+ with venv/pip first.' >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Python 3.9+ required")'
ROOT="$HOME/.local/share/orchard"
mkdir -p "$ROOT" "$HOME/.local/bin"
python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/python" -m pip install --upgrade --only-binary=:all: -r \
    https://github.com/OrchardLinux/cli/releases/latest/download/requirements.txt
ln -sfn "$ROOT/venv/bin/orchard" "$HOME/.local/bin/orchard"
export PATH="$HOME/.local/bin:$PATH"
orchard setup-host
orchard distros omarchy-a \
    https://github.com/OrchardLinux/omarchy-a/releases/latest/download/index.toml

# shellcheck disable=SC2016
printf '\nHost setup complete. If needed: export PATH="$HOME/.local/bin:$PATH"\n'
printf 'Next: prepare storage with Resize APFS, then run: orchard install omarchy-a\n'
