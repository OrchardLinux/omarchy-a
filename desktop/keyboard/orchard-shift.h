#ifndef ORCHARD_SHIFT_H
#define ORCHARD_SHIFT_H

#include <stdbool.h>
#include <stdint.h>

struct orchard_shift_tap {
    uint32_t at;
    bool pending;
};

/* Wayland event times are unsigned milliseconds and may wrap. A different
 * key cancels pending before this function is called again. Caps Lock never
 * holds Shift: punctuation/numbers keep their ordinary meanings. */
static inline uint8_t
orchard_shift_press(struct orchard_shift_tap *tap, uint8_t mods, uint32_t time,
                    uint8_t shift_mask, uint8_t caps_mask)
{
    if (mods & caps_mask) {
        mods &= ~(caps_mask | shift_mask);
        tap->pending = false;
    } else if (tap->pending && (mods & shift_mask) &&
               (uint32_t)(time - tap->at) <= 400) {
        mods = (mods & ~shift_mask) | caps_mask;
        tap->pending = false;
    } else {
        mods ^= shift_mask;
        tap->at = time;
        tap->pending = (mods & shift_mask) != 0;
    }
    return mods;
}

#endif
