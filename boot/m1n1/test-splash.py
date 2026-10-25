#!/usr/bin/env python3
"""Host-test the patched m1n1 draw block and its actual pixel conversion helpers.

Requires .work/j71b/source with patch and generated header. Not a hardware test.
"""
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
SRC = HERE / '.work/j71b/source/src'
source = (SRC / 'fb.c').read_text()
start = source.index('    /* Match Pongo\'s visible geometry; publish the complete frame only once. */')
renderer = source[start:source.index('\n#else', start)]
start = source.index('static inline u32 rgb2pixel_30')
helpers = source[start:source.index('static inline rgb_t fb_get_pixel', start)]
assert (SRC / 'omarchy-logo.h').read_bytes() == (
    HERE / '../pongo/.work/source/src/drivers/framebuffer/omarchy-logo.h').read_bytes()
program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "omarchy-logo.h"
typedef uint32_t u32;
typedef struct { uint8_t r, g, b; } rgb_t;
static struct { struct { u32 depth; } video; } cur_boot_args;
static struct { u32 *ptr, *hwptr, width, height, stride, size; } fb;
static unsigned updates;
static void memset32(void *ptr, u32 value, size_t bytes) {
    u32 *p = ptr;
    for (size_t i = 0; i < bytes / 4; ++i) p[i] = value;
}
static void fb_update(void) { ++updates; memcpy(fb.hwptr, fb.ptr, fb.size); }
HELPERS
static void draw(void) {
RENDERER
}
static void check(u32 width, u32 height, u32 stride, u32 depth) {
    const u32 sentinel = 0xdeadbeef;
    size_t count = (size_t)stride * height;
    u32 *allocation = malloc((count + 2) * 4);
    u32 *hardware = malloc((count + 2) * 4);
    assert(allocation && hardware);
    for (size_t i = 0; i < count + 2; ++i) allocation[i] = hardware[i] = sentinel;
    fb.ptr = allocation + 1; fb.hwptr = hardware + 1;
    fb.width = width; fb.height = height; fb.stride = stride; fb.size = count * 4;
    cur_boot_args.video.depth = depth;
    updates = 0;
    draw();
    assert(updates == 1);
    assert(allocation[0] == sentinel && allocation[count + 1] == sentinel);
    assert(hardware[0] == sentinel && hardware[count + 1] == sentinel);
    assert(!memcmp(fb.ptr, fb.hwptr, fb.size));
    size_t foreground = 0;
    for (u32 y = 0; y < height; ++y) {
        for (u32 x = 0; x < stride; ++x) {
            u32 expected = 0;
            if (width >= OMARCHY_LOGO_SIZE && height >= OMARCHY_LOGO_SIZE) {
                u32 left = (width - OMARCHY_LOGO_SIZE) / 2;
                u32 top = (height - OMARCHY_LOGO_SIZE) / 2;
                if (x >= left && x < left + OMARCHY_LOGO_SIZE &&
                    y >= top && y < top + OMARCHY_LOGO_SIZE) {
                    u32 bit = (y - top) * OMARCHY_LOGO_SIZE + x - left;
                    if (omarchy_logo_mask[bit / 8] & (0x80u >> (bit % 8))) {
                        expected = depth == 32 ? 0x009ece6a :
                            ((0x9eu << 22) | (0xceu << 12) | (0x6au << 2));
                        ++foreground;
                    }
                }
            }
            assert(fb.ptr[y * stride + x] == expected);
        }
    }
    if (width >= OMARCHY_LOGO_SIZE && height >= OMARCHY_LOGO_SIZE)
        assert(foreground > 0);
    else assert(foreground == 0);
    free(allocation); free(hardware);
}
int main(void) {
    assert(OMARCHY_LOGO_SIZE == 480);
    for (u32 depth = 30; depth <= 32; depth += 2) {
        check(1536, 2048, 1600, depth);
        check(2048, 1536, 2112, depth);
        check(480, 480, 480, depth);
        check(479, 800, 512, depth);
        check(800, 479, 832, depth);
        check(481, 483, 512, depth);
    }
    return 0;
}
'''.replace('HELPERS', helpers).replace('RENDERER', renderer)
with tempfile.TemporaryDirectory(prefix='m1n1-splash-') as temporary:
    root = Path(temporary)
    (root / 'test.c').write_text(program)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-function', '-fsanitize=address,undefined',
                    '-I', str(SRC), str(root / 'test.c'), '-o', str(root / 'test')],
                   check=True)
    subprocess.run([str(root / 'test')], check=True)
print('PASS: mask matches Pongo; 12 framebuffer cases; bounds, color and single publish')
