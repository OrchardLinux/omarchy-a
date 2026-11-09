"""Host checks for the patched keyboard's popup geometry and lifetime."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def added_source(filename):
    """Read added source from one file in the shipped zero-context patch."""
    patch = (ROOT / 'desktop/keyboard/wvkbd-0.20.patch').read_text()
    section = patch.split('+++ b/' + filename + '\n', 1)[1].split('\n--- ', 1)[0]
    return '\n'.join(line[1:] for line in section.splitlines()
                     if line.startswith('+') and not line.startswith('+++')) + '\n'


def compile_and_run(program, headers=None):
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        for name, source in (headers or {}).items():
            (folder / name).write_text(source)
        (folder / 'check.c').write_text(program)
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                        str(folder / 'check.c'), '-o', str(folder / 'check')], check=True,
                       capture_output=True, timeout=30)
        subprocess.run([str(folder / 'check')], check=True, capture_output=True, timeout=10)


class KeyPreviewGeometry(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'native C compiler required')
    def test_preview_geometry_at_edges_and_after_rotation(self):
        # Test the header actually shipped by the pinned-source patch, without
        # downloading upstream sources or requiring a running compositor.
        header = added_source('key-preview.h')
        program = r'''
#include <assert.h>
#include "key-preview.h"
int main(void) {
    const int widths[] = {320, 768, 1024, 1366};
    const int heights[] = {220, 270};
    for (unsigned i=0; i<sizeof(widths)/sizeof(widths[0]); i++) {
        for (unsigned j=0; j<sizeof(heights)/sizeof(heights[0]); j++) {
            int width=widths[i], height=heights[j], key_h=height/5;
            for (int key_w=24; key_w<=width; key_w+=24) {
                for (int x=0; x<=width-key_w; x+=7) {
                    for (int y=0; y+key_h<=height; y+=key_h) {
                        struct key_preview_bounds p=key_preview_place(width,height,x,y,key_w,key_h);
                        assert(p.x>=0 && p.x+p.w+3<=width);
                        assert(p.y>=0 && p.y+p.h+12<=2*height);
                        assert(p.w>=24 && p.w<=96 && p.h>=40 && p.h<=88);
                        assert(p.tip>=p.x+6 && p.tip<=p.x+p.w-6);
                    }
                }
            }
        }
    }
    struct key_preview_bounds empty=key_preview_place(0,270,0,0,48,54);
    assert(empty.w==0 && empty.h==0);
    return 0;
}
'''
        compile_and_run(program, {'key-preview.h': header})

    @unittest.skipUnless(shutil.which('cc'), 'native C compiler required')
    def test_hide_discards_popup_callback_before_destroying_surface(self):
        # Execute the production teardown with fake Wayland handles. No display,
        # downloaded source, or duplicate implementation of the cleanup is needed.
        main = added_source('main.c')
        signature = 'static void destroy_popup_surface(void)\n'
        cleanup = signature + main.split(signature, 1)[1].split('\n}\n', 1)[0] + '\n}\n'
        self.assertIn('    destroy_popup_surface();\n', main)
        stubs = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
struct wl_callback { int identity; };
struct wl_surface { int identity; };
static struct {
    struct wl_callback *frame_cb;
    struct wl_surface *surf;
    bool attached;
} popup_draw_surf;
static bool popup_xdg_surface_configured;
static struct { unsigned last_popup_w, last_popup_h; } keyboard;
static unsigned callbacks_destroyed, surfaces_destroyed;
static void wl_callback_destroy(struct wl_callback *callback) {
    assert(callback == popup_draw_surf.frame_cb);
    assert(popup_draw_surf.surf != NULL);
    callbacks_destroyed++;
}
static void wl_surface_destroy(struct wl_surface *surface) {
    assert(surface == popup_draw_surf.surf);
    assert(popup_draw_surf.frame_cb == NULL);
    assert(!popup_draw_surf.attached);
    surfaces_destroyed++;
}
'''
        program = r'''
int main(void) {
    struct wl_surface surface = {1};
    struct wl_callback callback = {1};
    for (unsigned cycle = 1; cycle <= 2; cycle++) {
        /* A new popup after show/rotation has its own pending frame. */
        popup_draw_surf.surf = &surface;
        popup_draw_surf.frame_cb = &callback;
        popup_draw_surf.attached = true;
        popup_xdg_surface_configured = true;
        keyboard.last_popup_w = 70;
        keyboard.last_popup_h = 80;
        destroy_popup_surface();
        assert(callbacks_destroyed == cycle && surfaces_destroyed == cycle);
        assert(popup_draw_surf.frame_cb == NULL && popup_draw_surf.surf == NULL);
        assert(!popup_draw_surf.attached && !popup_xdg_surface_configured);
        assert(keyboard.last_popup_w == 0 && keyboard.last_popup_h == 0);
        /* Repeated hide must not destroy an old handle again. */
        destroy_popup_surface();
        assert(callbacks_destroyed == cycle && surfaces_destroyed == cycle);
    }
    /* Hiding a popup before any preview has no callback to destroy. */
    popup_draw_surf.surf = &surface;
    popup_draw_surf.attached = true;
    destroy_popup_surface();
    assert(callbacks_destroyed == 2 && surfaces_destroyed == 3);
    return 0;
}
'''
        compile_and_run(stubs + cleanup + program)


if __name__ == '__main__':
    unittest.main()
