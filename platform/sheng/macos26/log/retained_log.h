/* SPDX-License-Identifier: MIT */
/* 诊断输出不等待锁，不依赖调度器；重入丢失单独计数 */
#ifndef SHENG_RETAINED_LOG_H
#define SHENG_RETAINED_LOG_H
#include <stddef.h>
#include <stdint.h>

#define SHENG_LOG_PREFIX 16384u
#define SHENG_LOG_TAIL 65536u
struct sheng_log_record {
    uint8_t magic[8];
    uint32_t version, header_bytes, prefix_bytes, tail_bytes;
    uint64_t total, dropped;
    uint32_t writer, panic_state;
    uint64_t physical_base, pc, sp, elr, esr, far, mpidr, image_va;
    uint8_t kernel_uuid[16];
    uint8_t prefix[SHENG_LOG_PREFIX], tail[SHENG_LOG_TAIL];
};
_Static_assert(offsetof(struct sheng_log_record, prefix) == 128, "log header ABI");
_Static_assert(offsetof(struct sheng_log_record, panic_state) == 44, "exception state ABI");
_Static_assert(offsetof(struct sheng_log_record, pc) == 56, "exception registers ABI");
_Static_assert(offsetof(struct sheng_log_record, kernel_uuid) == 112, "kernel UUID ABI");
struct sheng_log_record sheng_log_buffer __attribute__((aligned(16384))) = {
    .magic = {'S','H','N','L','O','G','0','1'}, .version = 1, .header_bytes = 128,
    .prefix_bytes = SHENG_LOG_PREFIX, .tail_bytes = SHENG_LOG_TAIL,
};
volatile uint32_t sheng_bootstrap_capture_enabled = 1;

void sheng_bootstrap_capture_end(void)
{
    __atomic_store_n(&sheng_bootstrap_capture_enabled, 0, __ATOMIC_RELEASE);
}

static void sheng_log_clean(const void *address, size_t bytes)
{
#if defined(__aarch64__)
    uintptr_t first = (uintptr_t)address & ~(uintptr_t)63;
    for (; first < (uintptr_t)address + bytes; first += 64)
        __asm__ volatile ("dc cvac, %0" :: "r"(first) : "memory");
    __asm__ volatile ("dsb sy" ::: "memory");
#else
    (void)address; (void)bytes;
#endif
}

void sheng_log_putc(char byte)
{
    struct sheng_log_record *r = &sheng_log_buffer;
    uint32_t expected = 0;
    if (!__atomic_compare_exchange_n(&r->writer, &expected, 1, 0,
                                     __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) {
        __atomic_fetch_add(&r->dropped, 1, __ATOMIC_RELAXED);
        sheng_log_clean(&r->dropped, sizeof(r->dropped));
        return;
    }
    uint64_t total = r->total;
    if (total == UINT64_MAX) {
        __atomic_fetch_add(&r->dropped, 1, __ATOMIC_RELAXED);
    } else {
        if (total < SHENG_LOG_PREFIX) {
            r->prefix[total] = (uint8_t)byte;
            sheng_log_clean(&r->prefix[total], 1);
        }
        r->tail[total % SHENG_LOG_TAIL] = (uint8_t)byte;
        sheng_log_clean(&r->tail[total % SHENG_LOG_TAIL], 1);
        __atomic_store_n(&r->total, total + 1, __ATOMIC_RELEASE);
    }
    __atomic_store_n(&r->writer, 0, __ATOMIC_RELEASE);
    sheng_log_clean(r, 64);
}

void sheng_log_begin(uint64_t physical_base, uint64_t virtual_base, const void *header)
{
    struct sheng_log_record *r = &sheng_log_buffer;
    const uint32_t *mh = header;
    r->physical_base = physical_base + (uintptr_t)r - virtual_base;
    r->image_va = (uintptr_t)header;
    if (mh[0] == 0xfeedfacf && mh[4] <= 4096 && mh[5] <= 1048576) {
        const uint8_t *cmd = (const uint8_t *)header + 32;
        const uint8_t *end = cmd + mh[5];
        for (uint32_t n = 0; n < mh[4] && (size_t)(end - cmd) >= 8; n++) {
            uint32_t words[2];
            __builtin_memcpy(words, cmd, sizeof(words));
            if (words[1] < 8 || words[1] > (size_t)(end - cmd)) break;
            if (words[0] == 0x1b && words[1] == 24) {
                for (unsigned i = 0; i < 16; i++) r->kernel_uuid[i] = cmd[8 + i];
                break;
            }
            cmd += words[1];
        }
    }
    sheng_log_clean(r, 128);
    const char *message = "\nSHENG-LOG: arm_init\n";
    while (*message) sheng_log_putc(*message++);
}

void sheng_log_panic(uint64_t caller, const char *message)
{
    struct sheng_log_record *r = &sheng_log_buffer;
    uint32_t expected = 0;
    if (__atomic_compare_exchange_n(&r->panic_state, &expected, 1, 0,
                                    __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) {
        r->pc = caller;
#if defined(__aarch64__)
        __asm__ volatile ("mov %0, sp" : "=r"(r->sp));
        __asm__ volatile ("mrs %0, elr_el1" : "=r"(r->elr));
        __asm__ volatile ("mrs %0, esr_el1" : "=r"(r->esr));
        __asm__ volatile ("mrs %0, far_el1" : "=r"(r->far));
        __asm__ volatile ("mrs %0, mpidr_el1" : "=r"(r->mpidr));
#endif
        __atomic_store_n(&r->panic_state, 2, __ATOMIC_RELEASE);
        sheng_log_clean(r, 128);
    }
    {
        const char *prefix = "\nSHENG-LOG: panic: ";
        while (*prefix) sheng_log_putc(*prefix++);
        for (unsigned n = 0; message && message[n] && n < 511; n++)
            sheng_log_putc(message[n]);
        sheng_log_putc('\n');
    }
    sheng_log_clean(r, sizeof(*r));
}
#endif
