#!/usr/bin/env python3
"""Make a 27×13 text logo from Omarchy's unmodified 54×26 logo."""
from pathlib import Path

root = Path(__file__).resolve().parent
rows = (root / "about.txt").read_text().splitlines()
assert len(rows) == 26 and all(len(row) == 54 and set(row) <= {" ", "█"} for row in rows)

compact = []
for y in range(0, 26, 2):
    line = ""
    for x in range(0, 54, 2):
        filled = sum(rows[y + dy][x + dx] == "█" for dy in range(2) for dx in range(2))
        line += "█" if filled >= 2 else " "
    compact.append(line)
assert len(compact) == 13 and all(len(row) == 27 for row in compact)
(root / "about-compact.txt").write_text("\n".join(compact) + "\n")
