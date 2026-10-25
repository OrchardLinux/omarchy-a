#!/usr/bin/env python3
"""Generate theme-tinted, one-pixel labwc XBM window-control glyphs."""
from pathlib import Path

size = 24
stroke = range(7, 17)
icons = {
    "iconify": {(x, 13) for x in stroke},
    "max": {(x, y) for x in stroke for y in stroke if x in (7, 16) or y in (7, 16)},
    "close": {(7 + n, 7 + n) for n in range(10)} | {(16 - n, 7 + n) for n in range(10)},
}
icons["max_toggled"] = icons["max"]

for name, pixels in icons.items():
    data = []
    for y in range(size):
        for start in range(0, size, 8):
            data.append(sum(1 << bit for bit in range(8) if (start + bit, y) in pixels))
    rows = [", ".join(f"0x{v:02x}" for v in data[i:i + 12]) for i in range(0, len(data), 12)]
    output = (f"#define {name}_width {size}\n#define {name}_height {size}\n"
              f"static unsigned char {name}_bits[] = {{\n  " + ",\n  ".join(rows) + "\n};\n")
    (Path(__file__).parent / f"{name}.xbm").write_text(output)
