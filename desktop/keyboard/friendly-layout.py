#!/usr/bin/env python3
"""Apply the reversible Orchard layout trial to a patched wvkbd v0.20 tree.

Retains upstream international/compose layouts and protocol/input handling.
Usage: friendly-layout.py SOURCE_DIRECTORY

The package build does not run this: it applies wvkbd-0.20-layout.patch, this
script's result. After a change here, regenerate that patch from a wvkbd v0.20
tree with wvkbd-0.20.patch applied (A) and a copy of it this ran on (B):
`diff -ruN A B`, file names without timestamps
(tests/test_keyboard_layout.py checks the two agree when WVKBD_SOURCE is set).
"""
import json
from pathlib import Path
import sys


def key(label, code, width=1, shifted=None, kind="Code", special=False, forced=None, target=None):
    # forced: a modifier the key always sends ("$" is Shift+4); target: the
    # layout a Layout key opens.
    return (label, shifted if shifted is not None else label, width, kind, code, special, forced, target)


def mod(label, code, width=1):
    # Same glyph and custom font as shell/plugins/menu/BarWidget.qml.
    return key("\ue900" if code == "Super" else label, code, width, kind="Mod", special=True)


def action(label, kind, width=1):
    return key(label, "0", width, kind=kind, special=True)


def letters(text):
    return [key(c, "KEY_" + c.upper(), shifted=c.upper()) for c in text]


def symbols(chars):
    codes = {"`": ("GRAVE", "~"), "-": ("MINUS", "_"), "=": ("EQUAL", "+"),
             "[": ("LEFTBRACE", "{"), "]": ("RIGHTBRACE", "}"),
             "\\": ("BACKSLASH", "|"), ";": ("SEMICOLON", ":"),
             "'": ("APOSTROPHE", '"'), ",": ("COMMA", "<"),
             ".": ("DOT", ">"), "/": ("SLASH", "?")}
    return [key(c, "KEY_" + codes[c][0], shifted=codes[c][1]) for c in chars]


PORTRAIT_WIDTH = 14.25

numbers = [key(c, "KEY_" + c, shifted=s) for c, s in zip("1234567890", "!@#$%^&*()")]
esc = key("Esc", "KEY_ESC", 1.25, special=True)
backspace = key("⌫", "KEY_BACKSPACE", 1.25, special=True)
enter = key("Enter", "KEY_ENTER", 2.5, special=True)
shift = mod("Shift", "Shift", 2)
arrows = [key(label, "KEY_" + code, special=True)
          for label, code in [("←", "LEFT"), ("↓", "DOWN"), ("→", "RIGHT")]]

# One shared letter/digit pitch, with compact physical-style offsets.
# Reuse the former Caps gutter for brackets, not an empty spacer. The extra
# half-unit budget enlarges Esc/Backspace without making punctuation tiny.
portrait = [
    [esc] + numbers + [key("-", "KEY_MINUS", .875, shifted="_"),
                       key("=", "KEY_EQUAL", .875, shifted="+"), backspace],
    [key("Tab", "KEY_TAB", 1.5, special=True)] + letters("qwertyuiop") +
    [key(";", "KEY_SEMICOLON", shifted=":"), key("\\", "KEY_BACKSLASH", 1.75, shifted="|")],
    [key("[", "KEY_LEFTBRACE", .875, shifted="{"), key("]", "KEY_RIGHTBRACE", .875, shifted="}")] +
    letters("asdfghjkl") + symbols("'") + [enter],
    [shift] + letters("zxcvbnm") + symbols(",./`") + [key("↑", "KEY_UP", 1.25, special=True)],
    [action("Fn", "NextLayer"), mod("Ctrl", "Ctrl"), mod("Alt", "Alt"), mod("Super", "Super"),
     key("space", "KEY_SPACE", 7.25)] + arrows,
]

landscape = [
    symbols("`") + numbers + symbols("-=") + [key("⌫", "KEY_BACKSPACE", 2, special=True)],
    [key("Tab", "KEY_TAB", 1.5, special=True)] + letters("qwertyuiop") + symbols(";") +
    [key("\\", "KEY_BACKSLASH", 2.5, shifted="|")],
    [key("[", "KEY_LEFTBRACE", .875, shifted="{"), key("]", "KEY_RIGHTBRACE", .875, shifted="}")] +
    letters("asdfghjkl") + symbols("'") + [key("Enter", "KEY_ENTER", 3.25, special=True)],
    [mod("Shift", "Shift", 2.25)] + letters("zxcvbnm") + symbols(",./") +
    [key("↑", "KEY_UP", special=True), mod("Shift", "Shift", 1.75)],
    [esc, action("Fn", "NextLayer"), mod("Ctrl", "Ctrl", 1.25), mod("Super", "Super", 1.25),
     mod("Alt", "Alt", 1.25), key("space", "KEY_SPACE", 6)] + arrows,
]


def more(wide=False):
    # Twelve function keys and a stable ABC return key in the Fn position.
    width = 15 if wide else PORTRAIT_WIDTH
    row1 = [key("F" + str(n), "KEY_F" + str(n), width / 12, special=True) for n in range(1, 13)]
    row2 = symbols("`-=[]\\;'/,.")
    row2 += [key("Del", "KEY_DELETE", width - len(row2), special=True)]
    row3 = [key(label, "KEY_" + code, width / 8, special=True) for label, code in
            [("Home", "HOME"), ("↑", "UP"), ("End", "END"), ("PgUp", "PAGEUP"),
             ("Ins", "INSERT"), ("PrtSc", "SYSRQ"), ("Menu", "COMPOSE"), ("⌫", "BACKSPACE")]]
    row4 = [mod("Shift", "Shift", 1.5), key("←", "KEY_LEFT", special=True),
            key("↓", "KEY_DOWN", special=True), key("→", "KEY_RIGHT", special=True),
            key("PgDn", "KEY_PAGEDOWN", 1.5, special=True),
            mod("AltGr", "AltGr", 1.5), key("Enter", "KEY_ENTER", width - 7.5, special=True)]
    row5 = [action("ABC", "NextLayer"), mod("Ctrl", "Ctrl"), mod("Alt", "Alt"), mod("Super", "Super"),
            key("space", "KEY_SPACE", width - 7)] + arrows
    if wide:
        row5 = [esc, action("ABC", "NextLayer"), mod("Ctrl", "Ctrl", 1.25),
                mod("Super", "Super", 1.25), mod("Alt", "Alt", 1.25),
                key("space", "KEY_SPACE", 6)] + arrows
    return [row1, row2, row3, row4, row5]


# A phone held upright: ten keys across, as on iOS, under a short row of the
# keys a terminal needs. 123 and #+= hold the symbols, each sent as the key
# (and Shift) that types it on a US keyboard, so they work in every app.
PHONE_WIDTH = 10


def typed(text):
    plain = {"-": "MINUS", "/": "SLASH", ";": "SEMICOLON", "'": "APOSTROPHE", ".": "DOT",
             ",": "COMMA", "[": "LEFTBRACE", "]": "RIGHTBRACE", "=": "EQUAL", "\\": "BACKSLASH",
             "`": "GRAVE"}
    shifted = {":": "SEMICOLON", "(": "9", ")": "0", "$": "4", "&": "7", "@": "2", '"': "APOSTROPHE",
               "?": "SLASH", "!": "1", "_": "MINUS", "|": "BACKSLASH", "{": "LEFTBRACE",
               "}": "RIGHTBRACE", "#": "3", "%": "5", "^": "6", "*": "8", "+": "EQUAL", "~": "GRAVE",
               "<": "COMMA", ">": "DOT"}
    if text in plain:
        return "KEY_" + plain[text], None
    return "KEY_" + shifted[text], "Shift"


def sym(text, width=1):
    code, forced = typed(text)
    return key(text, code, width, forced=forced)


def go(label, target, width):
    return key(label, "0", width, kind="Layout", special=True, target=target)


phone_tools = [key(label, "KEY_" + code, 1.25, special=True) for label, code in
               [("Esc", "ESC"), ("Tab", "TAB")]] + \
    [mod("Ctrl", "Ctrl", 1.25), mod("Alt", "Alt", 1.25)] + \
    [key(label, "KEY_" + code, 1.25, special=True) for label, code in
     [("←", "LEFT"), ("↓", "DOWN"), ("↑", "UP"), ("→", "RIGHT")]]
phone_backspace = key("⌫", "KEY_BACKSPACE", 1.5, special=True)
phone_enter = key("Enter", "KEY_ENTER", 2, special=True)
pad = key("", "0", .5, kind="Pad")


def phone_bottom(switch, left, right):
    return [switch, mod("Super", "Super", 1.25), left, key("space", "KEY_SPACE", 3.5), right, phone_enter]


phone = [
    phone_tools,
    letters("qwertyuiop"),
    [pad] + letters("asdfghjkl") + [pad],
    [key("⇧", "Shift", 1.5, shifted="⇫", kind="Mod", special=True)] + letters("zxcvbnm") + [phone_backspace],
    phone_bottom(go("123", "PhoneNum", 1.25), sym(","), sym(".")),
]
phone_punctuation = [sym(c, 1.4) for c in ".,?!'"] + [phone_backspace]
phone_num = [
    phone_tools,
    [key(c, "KEY_" + c) for c in "1234567890"],
    [sym(c) for c in '-/:;()$&@"'],
    [go("#+=", "PhoneSym", 1.5)] + phone_punctuation,
    phone_bottom(go("ABC", "Phone", 1.25), sym("_"), sym("|")),
]
phone_sym = [
    phone_tools,
    [sym(c) for c in "[]{}#%^*+="],
    [sym(c) for c in "\\~<>`"] + [key(label, "KEY_" + code, special=True) for label, code in
                                  [("Home", "HOME"), ("End", "END"), ("PgUp", "PAGEUP"), ("PgDn", "PAGEDOWN"),
                                   ("Del", "DELETE")]],
    [go("123", "PhoneNum", 1.5)] + phone_punctuation,
    phone_bottom(go("ABC", "Phone", 1.25), sym("_"), sym("|")),
]
# Each new layout: its enum name, wvkbd's name for it (-l), and whether it is
# a letters layout.
PHONE_LAYOUTS = {"keys_phone": ("Phone", "phone", True, phone),
                 "keys_phone_num": ("PhoneNum", "phonenum", False, phone_num),
                 "keys_phone_sym": ("PhoneSym", "phonesym", False, phone_sym)}

LAYOUTS = {"keys_full": portrait, "keys_special": more(),
           "keys_landscape": landscape, "keys_landscape_special": more(True)}


def validate():
    for name, rows in LAYOUTS.items():
        assert len(rows) == 5, name
        width = 15 if "landscape" in name else PORTRAIT_WIDTH
        for row in rows:
            assert abs(sum(k[2] for k in row) - width) < .0001, (name, row)
            assert all(k[2] > 0 for k in row)
        assert rows[-1][1 if "landscape" in name else 0][3] == "NextLayer"
        assert [k[4] for k in rows[-1][-3:]] == ["KEY_LEFT", "KEY_DOWN", "KEY_RIGHT"]
        assert not any(k[3] == "Layout" for row in rows for k in row)
    for name in ("keys_full", "keys_landscape"):
        positions = {}
        for row in LAYOUTS[name]:
            x = 0
            for k in row:
                positions[k[4]] = x
                if k[4] in {"KEY_" + c.upper() for c in "abcdefghijklmnopqrstuvwxyz0123456789"}:
                    assert k[2] == 1, (name, k)
                x += k[2]
        expected = [1.25, 1.5, 1.75, 2] if name == "keys_full" else [1, 1.5, 1.75, 2.25]
        assert [positions[c] for c in ("KEY_1", "KEY_Q", "KEY_A", "KEY_Z")] == expected
        assert not any(k[3] == "Mod" and k[4] == "CapsLock" for row in LAYOUTS[name] for k in row)
        codes = {k[4] for row in LAYOUTS[name] for k in row}
        assert {"KEY_" + c.upper() for c in "abcdefghijklmnopqrstuvwxyz0123456789"} <= codes
        assert {"KEY_ESC", "KEY_TAB", "KEY_SPACE", "KEY_BACKSPACE", "KEY_ENTER",
                "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_MINUS", "KEY_EQUAL",
                "KEY_GRAVE", "KEY_LEFTBRACE", "KEY_RIGHTBRACE", "KEY_SEMICOLON", "KEY_APOSTROPHE",
                "KEY_BACKSLASH", "KEY_COMMA", "KEY_DOT", "KEY_SLASH",
                "Ctrl", "Alt", "Super", "Shift"} <= codes


def validate_phone():
    for name, (_, _, _, rows) in PHONE_LAYOUTS.items():
        assert len(rows) == 5, name
        assert rows[0] == phone_tools, name
        for row in rows:
            assert abs(sum(k[2] for k in row) - PHONE_WIDTH) < .0001, (name, row)
        assert rows[-1][-1][4] == "KEY_ENTER" and rows[-1][3][4] == "KEY_SPACE", name
        targets = {k[7] for row in rows for k in row if k[3] == "Layout"}
        assert targets <= {v[0] for v in PHONE_LAYOUTS.values()}, (name, targets)
    codes = {k[4] for rows in (phone, phone_num) for row in rows for k in row}
    assert {"KEY_" + c.upper() for c in "abcdefghijklmnopqrstuvwxyz0123456789"} <= codes
    assert {"KEY_ESC", "KEY_TAB", "Ctrl", "Alt", "Super", "Shift", "KEY_BACKSPACE", "KEY_ENTER",
            "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT"} <= codes


def render(name, rows):
    lines = ["static struct key " + name + "[] = {"]
    for row_index, row in enumerate(rows):
        for label, shifted, width, kind, code, special, forced, layout in row:
            # Index links preserve upstream's international/compose chooser.
            target = ", .layout = &layouts[%s]" % (layout or "Index") if kind == "Layout" else ""
            target += ", .code_mod = " + forced if forced else ""
            scheme = (", .scheme = 2" if kind == "Mod" and code == "Super" else
                      ", .scheme = 4" if code in ("KEY_BACKSPACE", "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT") else
                      ", .scheme = 3" if code == "KEY_SPACE" else
                      ", .scheme = 1" if special else "")
            lines.append("  {%s, %s, %s, %s, %s%s%s}," %
                         (json.dumps(label, ensure_ascii=False), json.dumps(shifted, ensure_ascii=False),
                          width, kind, code, target, scheme))
        # wvkbd counts EndRow separators + 1, so never end the last row.
        if row_index < len(rows) - 1:
            lines.append('  {"", "", 0, EndRow},')
    lines.append('  {"", "", 0, Last},\n};')
    return "\n".join(lines)


# The phone's short top row: this share of a full row's height.
TOOLBAR_ROW = .55


def add_phone(text):
    """The phone layouts are new to wvkbd: name them, declare them, list them
    and add their keys after the landscape ones."""
    validate_phone()
    names = list(PHONE_LAYOUTS)
    enum = "".join("\t%s,\n" % PHONE_LAYOUTS[n][0] for n in names)
    assert text.count("\tLandscapeSpecial,\n") == 1
    text = text.replace("\tLandscapeSpecial,\n", "\tLandscapeSpecial,\n" + enum)
    assert text.count("keys_landscape_special[],") == 1
    text = text.replace("keys_landscape_special[],", "keys_landscape_special[], " +
                        ", ".join(n + "[]" for n in names) + ",")
    marker = '  [LandscapeSpecial] = {keys_landscape_special, "latin", "landscapespecial", true},\n'
    assert text.count(marker) == 1
    # The last field: the layout's first row is the short row (add_toolbar_row).
    entries = "".join('  [%s] = {%s, "latin", "%s", %s, 0, true},\n' %
                      (PHONE_LAYOUTS[n][0], n, PHONE_LAYOUTS[n][1], "true" if PHONE_LAYOUTS[n][2] else "false")
                      for n in names)
    text = text.replace(marker, marker + entries)
    start = text.index("static struct key keys_landscape_special[] = {")
    end = text.index("\n};", start) + len("\n};")
    rendered = "\n\n".join(render(n, PHONE_LAYOUTS[n][3]) for n in names)
    return text[:end] + "\n\n" + rendered + text[end:]


def add_toolbar_row(source):
    header = source / "keyboard.h"
    text = header.read_text()
    marker = "\tuint32_t keyheight; // absolute height (pixels)\n"
    assert text.count(marker) == 1
    header.write_text(text.replace(marker, marker + "\tbool toolbar; // Orchard: the first row is a short row\n"))
    code = source / "keyboard.c"
    text = code.read_text()
    old = """    l->keyheight = height / rows;

    struct key *k = l->keys;
    double rowlength = kbd_get_row_length(k);
    double rowwidth = 0.0;
    while (k->type != Last) {
        if (k->type == EndRow) {
            y += l->keyheight;"""
    new = """    /* Orchard: a toolbar layout's first row is %s of a row's height. */
    double units = rows - (l->toolbar ? 1 - %s : 0);
    l->keyheight = height / units;
    uint32_t rowheight = l->toolbar ? (uint32_t)(l->keyheight * %s) : l->keyheight;

    struct key *k = l->keys;
    double rowlength = kbd_get_row_length(k);
    double rowwidth = 0.0;
    while (k->type != Last) {
        if (k->type == EndRow) {
            y += rowheight;
            rowheight = l->keyheight;""" % (TOOLBAR_ROW, TOOLBAR_ROW, TOOLBAR_ROW)
    assert text.count(old) == 1
    text = text.replace(old, new)
    old = "        k->h = l->keyheight;\n        k++;"
    assert text.count(old) == 1
    code.write_text(text.replace(old, "        k->h = rowheight;\n        k++;"))


def apply(source):
    validate()
    layout = source / "layout.mobintl.h"
    text = layout.read_text()
    for name, rows in LAYOUTS.items():
        marker = "static struct key " + name + "[] = {"
        assert text.count(marker) == 1, marker
        start = text.index(marker)
        end = text.index("\n};", start) + len("\n};")
        text = text[:start] + render(name, rows) + text[end:]
    text = text.replace("#define KBD_KEY_BORDER 2", "#define KBD_KEY_BORDER 3")
    text = add_phone(text)
    layout.write_text(text)
    add_toolbar_row(source)
    config = source / "config.mobintl.h"
    text = config.read_text().replace("#define SHIFT_SPACE_IS_TAB", "/* Shift+Space remains a space; Tab has its own key. */")
    text = text.replace("#define DEFAULT_ROUNDING 5", "#define DEFAULT_ROUNDING 7")
    text = text.replace('#define SPECIAL_FONT "JetBrainsMono Nerd Font 13"',
                        '#define SPECIAL_FONT "JetBrainsMono Nerd Font 10"')
    # A dedicated font for the logo prevents a private-use glyph in the Nerd
    # Font from winning fallback resolution. Its colours are copied at runtime.
    if "/* Orchard logo font */" not in text:
        assert text.count("\n}\n};") == 1
        text = text.replace("\n}\n};", '\n},\n{.font = DEFAULT_FONT}, /* Orchard logo font */\n'
                            '{.font = SPECIAL_FONT} /* Orchard space label */\n};')
    text = text.replace("{0}, /* Orchard logo font */", "{.font = DEFAULT_FONT}, /* Orchard logo font */")
    text = text.replace("{0} /* Orchard space label */", "{.font = SPECIAL_FONT} /* Orchard space label */")
    if "/* Orchard editing icons */" not in text:
        text = text.replace("{.font = SPECIAL_FONT} /* Orchard space label */",
                            "{.font = SPECIAL_FONT}, /* Orchard space label */\n"
                            "{.font = DEFAULT_FONT} /* Orchard editing icons */")
    config.write_text(text)
    main = source / "main.c"
    text = main.read_text()
    marker = "    for (i = 0; i < countof(schemes); i++) {\n        schemes[i].font_description ="
    if "schemes[2] = schemes[1];" not in text:
        assert text.count(marker) == 1
        text = text.replace(marker, '    /* Inherit the active theme; only the Super label uses the logo font. */\n'
                            '    schemes[2] = schemes[1];\n    schemes[2].font = "omarchy 18";\n\n' + marker)
    if "schemes[3].font = SPECIAL_FONT;" not in text:
        text = text.replace('    schemes[2].font = "omarchy 18";',
                            '    schemes[2].font = "omarchy 18";\n'
                            '    schemes[3] = schemes[0];\n    schemes[3].font = SPECIAL_FONT;')
    text = text.replace('schemes[2].font = "omarchy 18";', 'schemes[2].font = "omarchy 14";')
    if "schemes[4].font = DEFAULT_FONT;" not in text:
        text = text.replace("    schemes[3].font = SPECIAL_FONT;",
                            "    schemes[3].font = SPECIAL_FONT;\n"
                            "    schemes[4] = schemes[1];\n    schemes[4].font = DEFAULT_FONT;")
    main.write_text(text)
    # Keep the gesture implementation separately testable without Wayland.
    import importlib.util
    spec = importlib.util.spec_from_file_location("orchard_shift_patch", Path(__file__).with_name("apply-shift.py"))
    shift_patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shift_patch)
    shift_patch.apply(source)


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        validate()
        for name, rows in LAYOUTS.items():
            rendered = render(name, rows)
            assert rendered.count("EndRow") == 4
            assert '"Super"' not in rendered
            assert '"\ue900", "\ue900"' in rendered
            assert "Mod, Super, .scheme = 2" in rendered
            assert "Code, KEY_SPACE, .scheme = 3" in rendered
        validate_phone()
        for name, (_, _, _, rows) in PHONE_LAYOUTS.items():
            assert render(name, rows).count("EndRow") == 4
        print("Four five-row layouts and three phone layouts: row separators, widths, letters, digits, modifiers and arrows OK")
    else:
        apply(Path(sys.argv[1]))
