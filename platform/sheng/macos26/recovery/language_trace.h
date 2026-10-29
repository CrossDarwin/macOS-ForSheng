// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

struct sheng_language_point {
    uint32_t rva;
    uint16_t tag;
    uint8_t destination;
    uint8_t branch;
    const char *name;
};

// Only the pinned CBNZ X0,+20 and MOV X19/X20/X24,X0 sites are replayable.
static inline int
sheng_language_step(const struct sheng_language_point *point, uint64_t x0)
{
    if (point->branch)
        return point->branch == 1 && !point->destination ? (x0 ? 20 : 4) : 0;
    return point->destination == 19 || point->destination == 20 || point->destination == 24 ? 4 : 0;
}
