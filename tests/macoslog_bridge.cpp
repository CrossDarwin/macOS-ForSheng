// SPDX-License-Identifier: GPL-3.0-or-later
#include "../platform/sheng/macos26/storage/macoslog_layout.h"
#include <cassert>

extern "C" bool check_fat(const uint8_t *image, uint64_t *first) {
    MlFat g;
    if (!mlFatGeometry(image, g)) return false;
    if (memcmp(image + g.reserved*4096, image + (g.reserved+g.fatBlocks)*4096, g.fatBlocks*4096)) return false;
    return mlFile(g, image + g.reserved*4096, image + g.rootFirst*4096, *first);
}
extern "C" bool check_gpt(const uint8_t *h, const uint8_t *e, const uint8_t *id, const uint8_t *type, bool backup) {
    return mlGptHeader(h, backup) && mlGptEntries(e, h, id, type);
}
extern "C" bool check_guard(const uint8_t *p, uint64_t first, const uint8_t *id, const uint8_t *part) {
    return mlGuard(p, first, id, part);
}
extern "C" bool commit(uint8_t *disk, uint64_t generation, uint8_t *payload, const uint8_t *id,
                       unsigned fail, unsigned *events) {
    struct Ops {
        uint8_t *disk; unsigned fail, calls=0; unsigned *events;
        bool write(uint64_t lba, unsigned blocks, const void *data) {
            assert(lba < 511 && blocks && blocks <= 511-lba);
            events[calls] = 0x10000 + unsigned(lba)*32 + blocks;
            bool bad = ++calls == fail;
            // A failed command may still have written a prefix to the medium.
            memcpy(disk + lba*4096, data, bad ? 17 : blocks*4096);
            return !bad;
        }
        bool sync() { events[calls] = 0x20000; return ++calls != fail; }
    } ops = {disk, fail, 0, events};
    uint8_t header[4096];
    return mlCommit(ops, 0, generation, payload, header, id);
}
