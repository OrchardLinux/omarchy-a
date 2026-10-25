#!/usr/bin/env python3
"""Render crisp, theme-coloured labwc SVG titlebar controls."""
from pathlib import Path
import os
import re
import sys

if len(sys.argv) != 3:
    sys.exit("Usage: render-labwc-buttons.py <colors.toml> <theme-dir>")
colors = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    match = re.fullmatch(r'\s*([\w-]+)\s*=\s*"(#[0-9a-fA-F]{6})"\s*(?:#.*)?', line)
    if match:
        colors[match.group(1)] = match.group(2)

out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
shapes = {
    "iconify": '<path d="M9 12H15"/>',
    "max": '<rect x="9" y="9" width="6" height="6"/>',
    "max_toggled": '<path d="M8 13V8H14V10M10 10H16V16H10Z"/>',
    "close": '<path d="M9 9L15 15M15 9L9 15"/>',
}
for state, color in (("active", colors["foreground"]),
                     ("inactive", colors["dark_foreground"])):
    for name, shape in shapes.items():
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
               f'<g fill="none" stroke="{color}" stroke-width="1" stroke-linecap="square">'
               f'{shape}</g></svg>\n')
        variant = f"{name}-{state}.svg"
        tmp = out / (variant + ".next")
        tmp.write_text(svg)
        os.chmod(tmp, 0o644)
        os.replace(tmp, out / variant)
        # Labwc draws its hover background only without a dedicated hover icon.
        (out / f"{name}_hover-{state}.svg").unlink(missing_ok=True)
