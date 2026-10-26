/* SPDX-License-Identifier: GPL-3.0-or-later */
#include <assert.h>
#include <string.h>
#include "../platform/sheng/macos26/log/boot_progress.h"

int main(void)
{
    struct sheng_boot_progress state = { .last_service = SHENG_BOOT_SERVICES };
    char lines[4][96];
    assert(sheng_boot_mark(&state, 0, 10));
    assert(sheng_boot_mark(&state, 1, 11));
    for (unsigned i = 0; i < 5000; i++) assert(!sheng_boot_mark(&state, 1, 12 + i));
    assert(state.changed == 11 && state.mask == 3);
    assert(!sheng_boot_service_event(&state, "WindowServerX", 50, 0, 0, 6000));
    assert(sheng_boot_service_event(&state, "WindowServer", 50, 0, 0, 6000));
    assert(state.changed == 6000 && state.mask == 0x43);
    assert(!sheng_boot_service_event(&state, "WindowServer", 50, 0, 0, 6001));
    assert(sheng_boot_service_event(&state, "WindowServer", 50, 1, 256, 6010));
    assert(!sheng_boot_service_event(&state, "WindowServer", 50, 1, 256, 6011));
    assert(sheng_boot_service_event(&state, "WindowServer", 51, 0, 0, 6020));
    assert(state.changed == 6000 && state.service[3].starts == 2 && state.service[3].exits == 1);
    assert(!sheng_boot_service_event(&state, "WindowServer", 50, 1, 256, 6021));
    state.now = 6100;
    state.log_state = 5; state.log_error = 17; state.generation = 73;
    sheng_boot_format(&state, 59551, 8, lines);
    assert(!strcmp(lines[0], "BOOT [##----#---] - WindowServer exec"));
    assert(strstr(lines[1], "100s - no loop verdict"));
    assert(strstr(lines[2], "starts=2 exits=1"));
    assert(strstr(lines[3], "stopped gen=73 bytes=59551 drops=8 error=17"));
    assert(!sheng_boot_mark(&state, 7, 6099));
    assert(!sheng_boot_mark(&state, 10, 6200));
    assert(sheng_boot_service_event(&state, "Language Chooser", 80, 0, 0, 6200));
    assert(state.changed == 6200);
    for (unsigned i = 0; i < SHENG_BOOT_SERVICES; i++)
        assert(sheng_boot_service_index(sheng_boot_service_names[i]) == (int)i);
    assert(sheng_boot_service_index(0) == -1);
    state.now = UINT64_MAX; state.changed = 0; state.generation = UINT64_MAX;
    state.events_lost = UINT64_MAX;
    sheng_boot_format(&state, UINT64_MAX, UINT64_MAX, lines);
    for (unsigned i = 0; i < 4; i++) assert(memchr(lines[i], 0, sizeof(lines[i])));
    return 0;
}
