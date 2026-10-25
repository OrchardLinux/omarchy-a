#!/usr/bin/env python3
"""Map the selected Omarchy palette to labwc's Openbox-style decorations.

Omarchy's compositor draws border-only windows; labwc retains titlebar controls
for mouse use, but shares the palette, 2px border, square corners and no shadow.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys


def values(path: Path, section: str | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    current = None
    for line in path.read_text().splitlines():
        header = re.fullmatch(r"\s*\[([^]]+)\]\s*", line)
        if header:
            current = header.group(1)
            continue
        if section is not None and current != section:
            continue
        match = re.fullmatch(r'\s*([\w-]+)\s*=\s*"(#[0-9a-fA-F]{6,8})"\s*(?:#.*)?', line)
        if match:
            result[match.group(1)] = match.group(2)
    return result


base = Path(__file__).resolve().parent
if len(sys.argv) == 1:
    colors_file, shell_file = base / "theme/colors.toml", base / "theme/shell.toml"
elif len(sys.argv) == 3:
    colors_file, shell_file = Path(sys.argv[1]), Path(sys.argv[2])
else:
    sys.exit("Usage: render-labwc-theme.py [colors.toml shell.toml]")
colors = values(colors_file)
hyprland = values(shell_file, "hyprland")
required = {"background", "dark_background", "lighter_background", "foreground", "dark_foreground", "selection", "accent"}
if missing := required - colors.keys():
    sys.exit(f"Missing palette keys: {', '.join(sorted(missing))}")
# labwc takes a solid border; use the first stop of an Omarchy gradient.
border = hyprland.get("active-border", colors["accent"])
first = re.search(r"#([0-9a-fA-F]{6})|rgba\(([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?\)", border)
if not first:
    sys.exit(f"Unsupported active border: {border}")
active = "#" + (first.group(1) or first.group(2))

print(f"""# Generated from Omarchy {colors_file.parent.name} colors.toml and shell.toml.
# Hyprland default/looknfeel.lua: 2px border, inactive #595959aa,
# rounding 0, shadow off, blur off. labwc keeps functional titlebar buttons.
border.width: 2
window.active.border.color: {active}
window.inactive.border.color: #595959aa
window.active.title.bg: Solid
window.active.title.bg.color: {colors['lighter_background']}
window.inactive.title.bg: Solid
window.inactive.title.bg.color: {colors['dark_background']}
window.active.label.text.color: {colors['foreground']}
window.inactive.label.text.color: {colors['dark_foreground']}
window.label.text.justify: Left
window.titlebar.padding.width: 10
window.titlebar.padding.height: 2
window.button.width: 24
window.button.height: 26
window.button.spacing: 2
window.active.button.unpressed.image.color: {colors['foreground']}
window.inactive.button.unpressed.image.color: {colors['dark_foreground']}
window.button.hover.bg.color: {active}33
window.button.hover.bg.corner-radius: 0
menu.items.bg.color: {colors['background']}
menu.items.text.color: {colors['foreground']}
menu.items.active.bg.color: {colors['selection']}
menu.items.active.text.color: {colors['foreground']}
menu.border.color: {active}
menu.border.width: 2
osd.bg.color: {colors['background']}
osd.label.text.color: {colors['foreground']}
osd.border.color: {active}
osd.border.width: 2
# Pixman uses an outline for snapping. Match Omarchy's focused border and
# background rather than labwc's unrelated default OSD preview colours.
snapping.overlay.edge.bg.enabled: no
snapping.overlay.region.bg.enabled: no
snapping.overlay.edge.border.enabled: yes
snapping.overlay.region.border.enabled: yes
snapping.overlay.edge.border.width: 2
snapping.overlay.region.border.width: 2
snapping.overlay.edge.border.color: {active},{colors['background']}
snapping.overlay.region.border.color: {active},{colors['background']}
""")
