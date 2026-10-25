#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$HOME/.local/share/orchard"
mkdir -p "$ROOT/logs" "$HOME/.local/bin"
LOG="$ROOT/logs/bootstrap-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
: > "$LOG"

step() {
    local label="$1" status
    shift
    if [ -t 1 ]; then
        printf '%s…' "$label"
    fi
    if "$@" >> "$LOG" 2>&1; then
        if [ -t 1 ]; then printf '\r\033[2K'; fi
        printf '✓ %s\n' "$label"
    else
        status=$?
        if [ -t 1 ]; then printf '\r\033[2K'; fi
        printf '✗ %s\n' "$label" >&2
        printf '\n' >&2
        tail -n 8 "$LOG" >&2
        printf '\nFull diagnostic log: %s\n' "$LOG" >&2
        exit "$status"
    fi
}

check_python() {
    command -v python3 >/dev/null || {
        printf 'Install Python 3.9+ with venv/pip first.\n' >&2
        return 1
    }
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Python 3.9+ required")'
}

register_distros() {
    "$ROOT/venv/bin/orchard" distros omarchy-a \
        https://github.com/OrchardLinux/omarchy-a/releases/latest/download/index.toml &&
    "$ROOT/venv/bin/orchard" distros minimal-linux \
        https://github.com/OrchardLinux/minimal-linux/releases/latest/download/index.toml
}

printf '\nOrchard · Host setup\n\n'
step 'Python ready' check_python
step 'Python environment ready' python3 -m venv "$ROOT/venv"
step 'Orchard installed' "$ROOT/venv/bin/python" -m pip install \
    --quiet --disable-pip-version-check --upgrade --only-binary=:all: -r \
    https://github.com/OrchardLinux/cli/releases/latest/download/requirements.txt
step 'Host tools ready' "$ROOT/venv/bin/orchard" setup-host
step 'Distributions registered' register_distros
step 'Orchard command ready' ln -sfn "$ROOT/venv/bin/orchard" "$HOME/.local/bin/orchard"

case ":$PATH:" in
    *":$HOME/.local/bin:"*) COMMAND=orchard ;;
    *) COMMAND='"$HOME/.local/bin/orchard"' ;;
esac
printf '\nEnter DFU, then choose an image to install:\n\n'
printf '  %s install omarchy-a\n' "$COMMAND"
printf '  %s install minimal-linux\n\n' "$COMMAND"
