#!/usr/bin/env python3
"""Compile the actual gesture-config selector with a named mapping fixture.

Run in the labwc builder: test-touch-config.py /source
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source = Path(sys.argv[1])
text = (source/'src/input/touch.c').read_text()
match = re.search(r'static struct touch_config_entry \*\nbottom_swipe_config\([^;{}]*\)\s*\{', text)
assert match
end = text.index('{', match.start()) + 1
depth = 1
while depth:
    if text[end] == '{': depth += 1
    if text[end] == '}': depth -= 1
    end += 1
function = text[match.start():end]
prefix = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <wayland-util.h>
#include <wlr/types/wlr_touch.h>
#include "config/touch.h"
static struct { struct wl_list touch_configs; } rc;
struct touch_config_entry *touch_find_config_for_device(char *name) {
    struct touch_config_entry *entry;
    wl_list_for_each_reverse(entry, &rc.touch_configs, link) {
        if (entry->device_name && !strcmp(entry->device_name,name)) return entry;
    }
    wl_list_for_each_reverse(entry, &rc.touch_configs, link) {
        if (!entry->device_name) return entry;
    }
    return NULL;
}
'''
test = r'''
int main(void) {
    wl_list_init(&rc.touch_configs);
    struct touch_config_entry defaults = {.bottom_swipe_command="keyboard show"};
    struct touch_config_entry mapped = {.device_name="iPad7,5 Touchscreen", .output_name="eDP-1"};
    wl_list_insert(&rc.touch_configs,&defaults.link);
    wl_list_insert(&rc.touch_configs,&mapped.link);
    struct wlr_touch touch = {.base.name="iPad7,5 Touchscreen"};
    assert(touch_find_config_for_device(touch.base.name) == &mapped);
    assert(bottom_swipe_config(&touch) == &defaults);
    mapped.bottom_swipe_command="";
    assert(bottom_swipe_config(&touch) == &mapped); /* explicit disable wins */
    mapped.bottom_swipe_command="other command";
    assert(bottom_swipe_config(&touch) == &mapped);
    mapped.bottom_swipe_command=NULL;
    defaults.bottom_swipe_command=NULL;
    assert(bottom_swipe_config(&touch) == NULL);
    puts("touch mapping: named output mapping inherits default swipe; explicit override/disable preserved");
}
'''
with tempfile.TemporaryDirectory(prefix='touch-config-') as tmp:
    root=Path(tmp);(root/'test.c').write_text(prefix+function+test)
    flags=subprocess.check_output(['pkg-config','--cflags','--libs','wlroots-0.20','wayland-server'],text=True).split()
    subprocess.run(['cc','-DWLR_USE_UNSTABLE','-Wall','-Wextra','-Werror','-I'+str(source/'include'),
                    str(root/'test.c'),'-o',str(root/'test'),*flags],check=True)
    subprocess.run([str(root/'test')],check=True)
