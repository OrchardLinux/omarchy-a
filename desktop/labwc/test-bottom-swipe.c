/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "input/bottom-swipe.h"

int main(void)
{
    struct bottom_swipe s;
    struct bottom_swipe_box portrait = {0, 0, 768, 1024};
    bottom_swipe_begin(&s, portrait, 300, 1020, 100, true);
    assert(s.pending);
    assert(bottom_swipe_motion(&s, portrait, 303, 1000, 150, true) == BOTTOM_WAIT);
    assert(bottom_swipe_motion(&s, portrait, 303, 975, 200, true) == BOTTOM_CLAIM);
    assert(bottom_swipe_motion(&s, portrait, 303, 930, 250, true) == BOTTOM_PASS);
    bottom_swipe_begin(&s, portrait, 300, 990, 100, true);
    assert(!s.pending); /* ordinary app scrolling */
    bottom_swipe_begin(&s, portrait, 300, 1020, 100, false);
    assert(!s.pending); /* locked, visible keyboard, missing config */
    bottom_swipe_begin(&s, portrait, 300, 1020, 100, true);
    assert(bottom_swipe_motion(&s, portrait, 340, 1010, 150, true) == BOTTOM_PASS);
    bottom_swipe_begin(&s, portrait, 300, 1020, 100, true);
    assert(bottom_swipe_motion(&s, portrait, 300, 970, 801, true) == BOTTOM_PASS);
    bottom_swipe_begin(&s, portrait, 300, 1020, 100, true);
    assert(bottom_swipe_motion(&s, portrait, 300, 975, 200, false) == BOTTOM_CANCEL);
    bottom_swipe_begin(&s, portrait, 300, 1020, 100, true);
    struct bottom_swipe_box landscape = {0, 0, 1024, 768};
    assert(bottom_swipe_motion(&s, landscape, 300, 720, 200, true) == BOTTOM_CANCEL);
    bottom_swipe_begin(&s, landscape, 700, 765, UINT32_MAX - 100, true);
    assert(bottom_swipe_motion(&s, landscape, 700, 720, 50, true) == BOTTOM_CLAIM);
    struct bottom_swipe_box second = {-1024, 200, 1024, 768};
    bottom_swipe_begin(&s, second, -500, 965, 0, true);
    assert(bottom_swipe_motion(&s, second, -500, 915, 100, true) == BOTTOM_CLAIM);
    bottom_swipe_begin(&s, portrait, 300, 1020, 100, true);
    s.pending = false; /* second contact / hardware cancellation */
    assert(bottom_swipe_motion(&s, portrait, 300, 970, 200, true) == BOTTOM_PASS);
    puts("bottom swipe: edge, threshold, once-only, direction, timeout, lock, rotation, output offset, clock wrap and cancellation OK");
}
