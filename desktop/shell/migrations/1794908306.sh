echo "Move to the omarchy-a package: the desktop runs from /usr/share/omarchy"

# Before the package, the image copied the desktop into ~/.local/share/omarchy-ipad
# and the session started it from there. A new user starts from /etc/skel and
# has this migration marked done.
old="$HOME/.local/share/omarchy-ipad"

# The session start is the package's now: ~/.config/labwc/autostart only runs
# it. An autostart that still starts the old copy is replaced (the old one is
# kept as a backup when it was changed).
autostart="$HOME/.config/labwc/autostart"
if [[ -f $autostart ]] && grep -q -e '\.local/share/omarchy-ipad' -e '/usr/local/libexec/' "$autostart"; then
  omarchy-refresh-config labwc/autostart
fi

# The Omarchy font is in the package's tree.
fonts="$HOME/.config/fontconfig/fonts.conf"
if [[ -f $fonts ]] && grep -q 'omarchy-ipad/default/fonts/omarchy' "$fonts"; then
  sed 's#omarchy-ipad/default/fonts/omarchy#omarchy/default/fonts/omarchy#' "$fonts" > "$fonts.new"
  mv -- "$fonts.new" "$fonts"
fi

# The terminal's launcher entry was a system file; it is the user's now, like
# upstream Omarchy's.
applications="$HOME/.local/share/applications"
if [[ ! -e $applications/foot.desktop ]]; then
  mkdir -p "$applications"
  cp "$OMARCHY_PATH/applications/foot.desktop" "$applications/foot.desktop"
fi

# The old copy, unless a session still runs from it (an update in a running
# session); it is only disk space then.
if [[ -d $old ]]; then
  if pgrep -u "$(id -u)" -f "$old/" >/dev/null; then
    echo "$old is still in use; remove it after logging out."
  else
    rm -rf -- "$old"
  fi
fi
