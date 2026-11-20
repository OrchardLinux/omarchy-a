echo "About shows the renderer with an icon"

# The Renderer line of About (fastfetch) had its name where every other line
# has a glyph; it has upstream's GPU glyph now. An existing
# ~/.config/fastfetch/config.jsonc gets it where the line is as shipped.
config="$HOME/.config/fastfetch/config.jsonc"
[[ -f $config ]] || exit 0
sed -i 's/"key": "│ ├Renderer",/"key": "│ ├\xee\x89\xa6",/' "$config"
