#include <assert.h>
#include <stdio.h>
#include "orchard-shift.h"

enum { Shift = 1, Caps = 2, Ctrl = 4, Alt = 8, Super = 64 };

int main(void)
{
    struct orchard_shift_tap tap = {0};
    uint8_t mods = orchard_shift_press(&tap, 0, 1000, Shift, Caps);
    assert(mods == Shift && tap.pending);             /* one capital */
    mods = orchard_shift_press(&tap, mods, 1200, Shift, Caps);
    assert(mods == Caps && !tap.pending);             /* double tap locks */
    mods = orchard_shift_press(&tap, mods, 1250, Shift, Caps);
    assert(mods == 0 && !tap.pending);                /* one tap unlocks */

    mods = orchard_shift_press(&tap, 0, 2000, Shift, Caps);
    mods = orchard_shift_press(&tap, mods, 2500, Shift, Caps);
    assert(mods == 0 && !tap.pending);                /* slow tap toggles off */

    mods = orchard_shift_press(&tap, 0, 3000, Shift, Caps);
    tap.pending = false;                             /* another key intervened */
    mods &= ~Shift;                                  /* single shift consumed */
    mods = orchard_shift_press(&tap, mods, 3150, Shift, Caps);
    assert(mods == Shift && !(mods & Caps));

    tap = (struct orchard_shift_tap){0};
    mods = orchard_shift_press(&tap, Ctrl | Alt | Super, UINT32_MAX - 100, Shift, Caps);
    mods = orchard_shift_press(&tap, mods, 99, Shift, Caps);
    assert(mods == (Caps | Ctrl | Alt | Super));       /* clock wraps, mods retained */
    mods = orchard_shift_press(&tap, mods, 150, Shift, Caps);
    assert(mods == (Ctrl | Alt | Super));

    tap = (struct orchard_shift_tap){0};
    mods = orchard_shift_press(&tap, 0, 5000, Shift, Caps);
    mods = orchard_shift_press(&tap, mods, 5400, Shift, Caps);
    assert(mods == Caps);                             /* inclusive 400ms boundary */
    puts("Shift: single, double, unlock, timeout, cancellation, wrap and modifiers OK");
    return 0;
}
