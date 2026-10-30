// SPDX-License-Identifier: GPL-3.0-or-later
#include <atomic>
#include <cassert>
#include <thread>
#include <vector>
#include "../platform/sheng/macos26/log/framebuffer_owner.h"
struct sheng_framebuffer_owner sheng_framebuffer{};

int main()
{
    std::atomic<unsigned> writers{0}, collisions{0};
    std::vector<std::thread> cores;
    for (unsigned cpu = 0; cpu < 8; cpu++) cores.emplace_back([&] {
        for (unsigned row = 0; row < 10000; row++) {
            uint64_t saved;
            if (!sheng_fb_begin(SHENG_FB_BOOT, &saved)) continue;
            if (writers.fetch_add(1) != 0) collisions++;
            writers--;
            sheng_fb_end(saved);
        }
    });
    for (auto &core : cores) core.join();
    assert(collisions == 0);
    uint64_t saved, other;
    assert(sheng_fb_begin(SHENG_FB_BOOT, &saved));
    assert(!sheng_fb_claim_gui());
    sheng_fb_end(saved);
    assert(sheng_fb_claim_gui());
    assert(!sheng_fb_begin(SHENG_FB_BOOT, &saved));
    assert(sheng_fb_begin(SHENG_FB_GUI, &saved));
    // A synchronous fault can interrupt the lease holder: panic must not acquire it.
    sheng_fb_enter_panic();
    assert(sheng_framebuffer.writer == 1);
    assert(!sheng_fb_begin(SHENG_FB_GUI, &other));
    sheng_fb_abort_gui();
    assert(sheng_framebuffer.owner == SHENG_FB_PANIC);
    sheng_fb_end(saved);
    assert(!sheng_fb_begin(SHENG_FB_BOOT, &saved));
    assert(!sheng_fb_begin(SHENG_FB_GUI, &saved));
    assert(!sheng_fb_claim_gui());
}
