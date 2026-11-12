#!/usr/bin/env python3
"""Compile the actual gesture callbacks against event/drawing spies, no Wayland.

Usage: test-press-feedback.py /path/to/patched/wvkbd/main.c
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def function(source, name):
    # These small C callbacks contain no string/comment brace literals.
    match = re.search(r"\b" + re.escape(name) + r"\([^;{}]*\)\s*\{", source)
    assert match, name
    start = match.start()
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return "static void " + source[start:end]


PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>

enum drag_source { DRAG_NONE, DRAG_POINTER, DRAG_TOUCH };
enum { Press = 1 };
struct wl_touch { int unused; };
struct wl_pointer { int unused; };
struct wl_surface { int unused; };
struct key { int unused; };
struct kbd {
    bool show_popup;
    int mods, compose, last_abc_index;
    void *prevlayout;
};
static struct kbd keyboard;
static struct key test_key;
static enum drag_source pending_source, drag_source;
static int32_t pending_id, drag_touch_id;
static int pending_x, pending_y, cur_x, cur_y;
static uint32_t pending_time, drag_last_time;
static int64_t pending_started;
static bool pending_preview_visible;
static bool layer_surface_configured = true, popup_xdg_surface_configured = true;
static int pressed, released, draws, redraws, moved, dragged, finished;
static uint32_t emitted_time;
static int64_t monotonic_ms(void) { return 100; }
static struct key *kbd_get_key(struct kbd *kb, int x, int y) {
    (void)kb;
    return x >= 0 && x < 100 && y >= 0 && y < 100 ? &test_key : NULL;
}
static void kbd_draw_key(struct kbd *kb, struct key *key, int type) {
    assert(key == &test_key && type == Press);
    assert(!kb->show_popup); /* preview must not bring back magnifier popups */
    draws++;
}
static void kbd_draw_layout(struct kbd *kb) { (void)kb; redraws++; }
static void kbd_unpress_key(struct kbd *kb, uint32_t time) { (void)kb; (void)time; }
static void kbd_press_key(struct kbd *kb, struct key *key, uint32_t time) {
    (void)kb; assert(key == &test_key); pressed++; emitted_time = time;
}
static void kbd_release_key(struct kbd *kb, uint32_t time) { (void)kb; (void)time; released++; }
static void kbd_switch_layout(struct kbd *kb, void *layout, int index) {
    (void)kb; (void)layout; (void)index;
}
static void drag_begin(enum drag_source source, int32_t id, int y, uint32_t time) {
    (void)id; (void)y; (void)time;
    assert(!pending_preview_visible && redraws == 1);
    drag_source = source; dragged++;
}
static void drag_motion(int y, uint32_t time) { (void)y; (void)time; }
static void drag_finish(bool cancelled, uint32_t time) { (void)cancelled; (void)time; finished++; }
static void kbd_motion_key(struct kbd *kb, uint32_t time, int x, int y) {
    (void)kb; (void)time; (void)x; (void)y; moved++;
}
static bool animating;
'''

TESTS = r'''
static void reset(void) {
    keyboard = (struct kbd){.show_popup = true, .mods = 2}; /* Caps already latched */
    pending_source = drag_source = DRAG_NONE;
    pending_preview_visible = animating = false;
    pressed = released = draws = redraws = moved = dragged = finished = 0;
}
int main(void) {
    reset();
    pending_begin(DRAG_TOUCH, 7, 20, 20, 1000);
    assert(draws == 1 && pressed == 0 && pending_preview_visible);
    assert(keyboard.show_popup && keyboard.mods == 2);
    pending_motion(22, 23, 1020);
    assert(pressed == 0 && pending_preview_visible);
    wl_touch_up(NULL, NULL, 0, 1050, 8); /* unrelated finger */
    assert(pressed == 0 && pending_preview_visible);
    wl_touch_up(NULL, NULL, 0, 1060, 7);
    assert(pressed == 1 && released == 1 && emitted_time == 1000);
    assert(!pending_preview_visible && pending_source == DRAG_NONE);

    reset();
    pending_begin(DRAG_TOUCH, 7, 20, 20, 2000);
    pending_motion(21, 35, 2020); /* downward swipe */
    assert(dragged == 1 && pressed == 0 && redraws == 1);
    assert(!pending_preview_visible && keyboard.mods == 2);

    reset();
    pending_begin(DRAG_TOUCH, 7, 20, 20, 3000);
    wl_touch_cancel(NULL, NULL);
    assert(redraws == 1 && pressed == 0 && !pending_preview_visible);
    assert(pending_source == DRAG_NONE && keyboard.mods == 2);

    reset();
    pending_begin(DRAG_POINTER, 0, 20, 20, 4000);
    wl_pointer_leave(NULL, NULL, 0, NULL);
    assert(redraws == 1 && pressed == 0 && !pending_preview_visible);
    assert(pending_source == DRAG_NONE && cur_x == -1 && cur_y == -1);

    reset();
    pending_begin(DRAG_TOUCH, 7, 20, 20, 5000);
    pending_commit(); /* long-hold deadline follows this same path */
    pending_commit();
    assert(pressed == 1 && !pending_preview_visible && draws == 1);

    reset();
    pending_begin(DRAG_TOUCH, 7, 200, 200, 6000); /* padding/outside a key */
    assert(draws == 0 && !pending_preview_visible && pressed == 0);
    wl_touch_cancel(NULL, NULL);
    assert(redraws == 0);

    puts("Press feedback: immediate draw, deferred input, tap/hold, swipe, cancel, pointer leave and latched modifiers OK");
}
'''


def main():
    source = Path(sys.argv[1]).read_text()
    functions = "\n\n".join(function(source, name) for name in
                             ("pending_preview_clear", "pending_begin", "pending_commit", "pending_motion",
                              "wl_touch_up", "wl_touch_cancel", "wl_pointer_leave"))
    # Callback names also appear in forward declarations: select definitions.
    assert "void wl_touch_up(" in functions
    compiler = shutil.which("cc")
    if not compiler:
        raise SystemExit("A host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="wvkbd-feedback-") as tmp:
        root = Path(tmp)
        test = root / "test.c"
        test.write_text(PREFIX + functions + TESTS)
        subprocess.run([compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-parameter", str(test), "-o", str(root / "test")], check=True)
        subprocess.run([str(root / "test")], check=True)


if __name__ == "__main__":
    main()
