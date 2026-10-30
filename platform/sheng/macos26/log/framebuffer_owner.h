/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SHENG_FRAMEBUFFER_OWNER_H
#define SHENG_FRAMEBUFFER_OWNER_H
#include <stdint.h>

#define SHENG_FB_BOOT 0u
#define SHENG_FB_GUI 1u
#define SHENG_FB_PANIC 2u
struct sheng_framebuffer_owner { uint32_t owner, writer; };
#ifdef __cplusplus
extern "C" {
#endif
extern struct sheng_framebuffer_owner sheng_framebuffer;
#ifdef __cplusplus
}
#endif

/* A lease covers wired pixel stores only; allocation, mapping and source reads precede it. */
static inline int sheng_fb_begin(unsigned owner, uint64_t *saved)
{
    *saved = 0;
#if defined(__aarch64__)
    __asm__ volatile("mrs %0, daif\nmsr daifset, #7" : "=r"(*saved) :: "memory");
#endif
    uint32_t expected = 0;
    if (__atomic_compare_exchange_n(&sheng_framebuffer.writer, &expected, 1, 0,
            __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) {
        if (__atomic_load_n(&sheng_framebuffer.owner, __ATOMIC_ACQUIRE) == owner) return 1;
        __atomic_store_n(&sheng_framebuffer.writer, 0, __ATOMIC_RELEASE);
    }
#if defined(__aarch64__)
    __asm__ volatile("msr daif, %0" :: "r"(*saved) : "memory");
#endif
    return 0;
}

static inline void sheng_fb_end(uint64_t saved)
{
#if defined(__aarch64__)
    __asm__ volatile("dsb sy" ::: "memory");
#endif
    __atomic_store_n(&sheng_framebuffer.writer, 0, __ATOMIC_RELEASE);
#if defined(__aarch64__)
    __asm__ volatile("msr daif, %0" :: "r"(saved) : "memory");
#else
    (void)saved;
#endif
}

static inline int sheng_fb_claim_gui(void)
{
    uint64_t saved;
    if (!sheng_fb_begin(SHENG_FB_BOOT, &saved)) return 0;
    uint32_t expected = SHENG_FB_BOOT;
    int claimed = __atomic_compare_exchange_n(&sheng_framebuffer.owner, &expected,
        SHENG_FB_GUI, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED);
    sheng_fb_end(saved);
    return claimed;
}

static inline void sheng_fb_abort_gui(void)
{
    /* Only the serialized first-frame caller may roll back; panic is irreversible. */
    uint32_t expected = SHENG_FB_GUI;
    __atomic_compare_exchange_n(&sheng_framebuffer.owner, &expected, SHENG_FB_BOOT,
        0, __ATOMIC_RELEASE, __ATOMIC_RELAXED);
}

static inline void sheng_fb_enter_panic(void)
{
    /* Never wait for a faulted or interrupted writer. Redraw after CPU rendezvous. */
    __atomic_store_n(&sheng_framebuffer.owner, SHENG_FB_PANIC, __ATOMIC_RELEASE);
}
#endif
