#!/usr/bin/env python3
"""Apply tested double-tap Shift behaviour to wvkbd v0.20, idempotently."""
from pathlib import Path
import shutil


def replace(path, old, new):
    text = path.read_text()
    if new in text:
        return
    assert text.count(old) == 1, (path, old)
    path.write_text(text.replace(old, new))


def apply(source):
    shutil.copy2(Path(__file__).with_name("orchard-shift.h"), source / "orchard-shift.h")
    header = source / "keyboard.h"
    replace(header, "#define MAX_LAYERS 25\n",
            '#define MAX_LAYERS 25\n#include "orchard-shift.h"\n')
    replace(header, "\tuint8_t mods;\n",
            "\tuint8_t mods;\n\tstruct orchard_shift_tap shift_tap;\n")
    keyboard = source / "keyboard.c"
    replace(keyboard,
            "kbd_press_key(struct kbd *kb, struct key *k, uint32_t time)\n{\n",
            "kbd_press_key(struct kbd *kb, struct key *k, uint32_t time)\n{\n"
            "    /* Only consecutive Shift taps may lock capitals. */\n"
            "    if (k->type != Mod || k->code != Shift)\n"
            "        kb->shift_tap.pending = false;\n")
    replace(keyboard,
            "    case Mod:\n        kb->mods ^= k->code;",
            "    case Mod:\n"
            "        if (k->code == Shift) {\n"
            "            uint8_t before = kb->mods;\n"
            "            kb->mods = orchard_shift_press(&kb->shift_tap, before, time, Shift, CapsLock);\n"
            "            uint8_t released = before & ~kb->mods;\n"
            "            uint8_t pressed = kb->mods & ~before;\n"
            "            if (released)\n"
            "                zwp_virtual_keyboard_v1_key_mods(kb->vkbd, time, released, WL_KEYBOARD_KEY_STATE_RELEASED);\n"
            "            if (pressed)\n"
            "                zwp_virtual_keyboard_v1_key_mods(kb->vkbd, time, pressed, WL_KEYBOARD_KEY_STATE_PRESSED);\n"
            "            zwp_virtual_keyboard_v1_modifiers(kb->vkbd, kb->mods, 0, 0, 0);\n"
            "            kbd_draw_layout(kb);\n"
            "            break;\n"
            "        }\n"
            "        kb->mods ^= k->code;")
    replace(keyboard,
            '    if (kb->debug)\n        fprintf(stderr, "Draw key',
            '    if (k->type == Mod && k->code == Shift && (kb->mods & CapsLock))\n'
            '        label = "Caps";\n'
            '    if (kb->debug)\n        fprintf(stderr, "Draw key')
    replace(keyboard,
            "        if ((next_key->type == Mod && kb->mods & next_key->code) ||\n",
            "        if ((next_key->type == Mod && kb->mods & next_key->code) ||\n"
            "            (next_key->type == Mod && next_key->code == Shift && (kb->mods & CapsLock)) ||\n")
    replace(keyboard,
            "        if (!invert)\n            kb->mods ^= Shift;",
            "        if (!invert && (kb->mods & Shift))\n            kb->mods ^= Shift;")
