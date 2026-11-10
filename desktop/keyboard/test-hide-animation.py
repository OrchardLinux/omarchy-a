#!/usr/bin/env python3
"""Exercise actual wvkbd hide/tick callbacks without a Wayland compositor."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def function(source, name):
    match = re.search(r'\b' + name + r'\([^;{}]*\)\s*\{', source)
    assert match
    start = match.start()
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        if source[end] == '{': depth += 1
        if source[end] == '}': depth -= 1
        end += 1
    return 'static void ' + source[start:end]


source = Path(sys.argv[1]).read_text()
assert 'else if (si.ssi_signo == SIGUSR1)\n                request_hide();' in source
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
enum { DRAG_NONE, DRAG_TOUCH };
static void *layer_surface;
static bool layer_surface_configured, animating, animation_hide, cur_press;
static int pending_source, drag_source, animation_from, animation_to, drag_offset;
static uint32_t height = 270;
static int64_t animation_started, now;
static int keyboard, releases, clears, hides;
static int64_t monotonic_ms(void) { return now; }
static void pending_preview_clear(void) { clears++; }
static void kbd_release_key(int *kb, uint32_t time) { (void)kb; (void)time; releases++; }
static void drag_position(int offset) { drag_offset = offset; }
static void hide(void) { hides++; animating = false; layer_surface = NULL; }
'''
tests = r'''
int main(void) {
    layer_surface = &keyboard;
    layer_surface_configured = true;
    cur_press = true;
    pending_source = drag_source = DRAG_TOUCH;
    now = 1000;
    request_hide();
    assert(hides == 0 && animating && animation_hide);
    assert(animation_from == 0 && animation_to == 270);
    assert(!cur_press && pending_source == DRAG_NONE && drag_source == DRAG_NONE);
    assert(releases == 1 && clears == 1);
    now = 1090;
    animation_tick();
    assert(drag_offset > 0 && drag_offset < 270 && hides == 0);
    request_hide(); /* repeated hide must not restart or stall it */
    assert(animation_started == 1000 && releases == 1);
    now = 1180;
    animation_tick();
    assert(hides == 1 && !animating && !layer_surface && drag_offset == 270);
    request_hide();
    assert(hides == 1);
    layer_surface = &keyboard;
    layer_surface_configured = false;
    request_hide(); /* no configured buffer: safe immediate teardown */
    assert(hides == 2 && !layer_surface);
    puts("hide: animated request, intermediate position, final teardown, repeated requests and unconfigured surface OK");
}
'''
with tempfile.TemporaryDirectory(prefix='wvkbd-hide-test-') as tmp:
    root = Path(tmp)
    test = root / 'test.c'
    test.write_text(prefix + function(source, 'request_hide') + function(source, 'animation_tick') + tests)
    subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', str(test), '-o', str(root/'test')], check=True)
    subprocess.run([str(root/'test')], check=True)
