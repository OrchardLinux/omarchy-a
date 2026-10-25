#!/usr/bin/env python3
"""Host-test the exact patched draw block against padded/small framebuffers.

Run after applying the patch and generating omarchy-logo.h in .work/source.
This is not a full Pongo build or a hardware/pixel-format test.
"""
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
FB = HERE / '.work/source/src/drivers/framebuffer'
source = (FB / 'fb.c').read_text()
start = source.index('    /* Keep row stride distinct from the visible width. */')
end = source.index('\n#else', start)
renderer = source[start:end]
program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include "omarchy-logo.h"
static uint32_t *gFramebuffer, gWidth, gHeight, gRowPixels, basecolor;
static void screen_fill(uint32_t color) {
    for (uint32_t y = 0; y < gHeight; ++y)
        for (uint32_t x = 0; x < gWidth; ++x)
            gFramebuffer[y * gRowPixels + x] = color;
}
static void draw(void) {
RENDERER
}
static void check(uint32_t width, uint32_t height, uint32_t stride) {
    const uint32_t sentinel = 0xdeadbeef;
    const size_t count = (size_t)stride * height;
    uint32_t *allocation = malloc((count + 2) * sizeof(uint32_t));
    assert(allocation);
    for (size_t i = 0; i < count + 2; ++i) allocation[i] = sentinel;
    gFramebuffer = allocation + 1;
    gWidth = width; gHeight = height; gRowPixels = stride;
    draw();
    assert(allocation[0] == sentinel && allocation[count + 1] == sentinel);
    size_t foreground = 0;
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < stride; ++x) {
            uint32_t expected = x >= width ? sentinel : 0;
            if (width >= 600 && height >= 600) {
                const uint32_t left = (width - 600) / 2;
                const uint32_t top = (height - 600) / 2;
                if (x >= left && x < left + 600 && y >= top && y < top + 600) {
                    const uint32_t bit = (y - top) * 600 + x - left;
                    if (omarchy_logo_mask[bit / 8] & (0x80u >> (bit % 8)))
                        expected = 0x009ece6a;
                }
            }
            assert(gFramebuffer[y * stride + x] == expected);
            foreground += expected == 0x009ece6a;
        }
    }
    if (width >= 600 && height >= 600) assert(foreground > 0);
    else assert(foreground == 0);
    free(allocation);
}
int main(void) {
    assert(sizeof(omarchy_logo_mask) == 45000);
    check(1536, 2048, 1600);
    check(2048, 1536, 2112);
    check(600, 600, 600);
    check(599, 800, 640);
    check(800, 599, 832);
    check(601, 603, 640);
    return 0;
}
'''.replace('RENDERER', renderer)
for literal, replacement in {
    '45000': '(OMARCHY_LOGO_SIZE * OMARCHY_LOGO_SIZE / 8)',
    '600': 'OMARCHY_LOGO_SIZE',
    '599': '(OMARCHY_LOGO_SIZE - 1)',
}.items():
    program = re.sub(r'\b' + literal + r'\b', replacement, program)
with tempfile.TemporaryDirectory(prefix='pongo-renderer-') as temporary:
    root = Path(temporary)
    (root / 'test.c').write_text(program)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(FB),
                    str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
print('PASS: six framebuffer geometries; bounds, padding, centering and mask size')
