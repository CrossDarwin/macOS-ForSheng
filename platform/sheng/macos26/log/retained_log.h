/* SPDX-License-Identifier: MIT */
/* Diagnostic output never waits for locks or scheduling; count reentrant drops separately. */
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
uint64_t sheng_bootstrap_fb_l2[2048] __attribute__((aligned(16384)));
uint64_t sheng_bootstrap_fb_trace_ready;
volatile uint64_t sheng_bootstrap_c_stage = UINT64_MAX;
volatile uint64_t sheng_bootstrap_vm_stage = UINT64_MAX;
volatile uint64_t sheng_bootstrap_vm_pixels;
uint64_t sheng_bootstrap_vm_row_pa, sheng_bootstrap_vm_stride;
volatile uint64_t sheng_bootstrap_vm_witness;
#include "pe_sheng_panel.h"

void sheng_bootstrap_capture_end(void)
{
    __atomic_store_n(&sheng_bootstrap_capture_enabled, 0, __ATOMIC_RELEASE);
}

static void sheng_log_clean(const volatile void *address, size_t bytes)
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
        sheng_panel_putc((unsigned char)byte);
    }
    __atomic_store_n(&r->writer, 0, __ATOMIC_RELEASE);
    sheng_log_clean(r, 64);
}

volatile uint64_t sheng_panel_bound_rows;
#include "pe_sheng_boot_progress_kernel.h"

unsigned sheng_log_snapshot_copy(void *destination, unsigned bytes);
unsigned sheng_log_snapshot_copy(void *destination, unsigned bytes)
{
    sheng_boot_progress_tick();
    struct sheng_log_record *r = &sheng_log_buffer;
    uint32_t expected = 0;
    if (!destination || bytes != sizeof(*r) ||
        !__atomic_compare_exchange_n(&r->writer, &expected, 1, 0,
                                    __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) return 0;
    /* Copy RAM only; never issue storage commands or render while holding the writer. */
    __builtin_memcpy(destination, r, sizeof(*r));
    ((struct sheng_log_record *)destination)->writer = 0;
    __atomic_store_n(&r->writer, 0, __ATOMIC_RELEASE);
    return sizeof(*r);
}

void sheng_log_bind_panic_panel(uintptr_t address, unsigned stride, unsigned columns,
    unsigned rows, unsigned scale)
{
    if (!address || stride < 2560 || stride > 65536 || columns < 32 || columns > 100 ||
        rows < 6 || rows > 16 || (scale != 1 && scale != 2) || columns * 8 * scale * 4 > stride) return;
    sheng_panic_panel.base = address;
    sheng_panic_panel.stride = stride;
    sheng_panic_panel.columns = columns;
    sheng_panic_panel.rows = rows;
    sheng_panic_panel.scale = scale;
    sheng_panic_panel_bound_rows = rows;
    sheng_panic_panel_render();
}

void sheng_log_bind_panel(uintptr_t address, unsigned stride, unsigned columns,
    unsigned rows, unsigned scale)
{
    struct sheng_log_record *r = &sheng_log_buffer;
    uint32_t expected = 0;
    if (!address || stride < 2560 || stride > 65536 || columns < 32 || columns > 100 ||
        (rows < 6 || rows > 24) || (scale != 1 && scale != 2) || columns * 8 * scale * 4 > stride ||
        !__atomic_compare_exchange_n(&r->writer, &expected, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) return;
    sheng_panel.base = address;
    sheng_panel.stride = stride;
    sheng_panel.columns = columns;
    sheng_panel.rows = rows;
    sheng_panel_bound_rows = rows;
    sheng_panel.scale = scale;
    sheng_panel_ready = 1;
    sheng_panel_reset();
    /* Replay only a bounded tail; pin the first panic line separately so long backtraces cannot overwrite it. */
    const uint64_t total = r->total;
    uint64_t start = total > 512 ? total - 512 : 0;
    if (start) {
        while (start < total && r->tail[start % SHENG_LOG_TAIL] != '\n') start++;
        if (start < total) start++;
    }
    for (; start < total; start++) sheng_panel_putc(r->tail[start % SHENG_LOG_TAIL]);
    __atomic_store_n(&r->writer, 0, __ATOMIC_RELEASE);
}

void sheng_log_repaint_panel(void)
{
    if (sheng_panel_ready && !sheng_status_pinned) {
        sheng_log_bind_panel(sheng_panel.base, sheng_panel.stride, sheng_panel.columns,
            sheng_panel.rows, sheng_panel.scale);
    }
}

volatile uint64_t sheng_first_sync_displayed;
static void sheng_exception_text(const char *message)
{
    /* Send first-fault registers to the independent display path even if the fault interrupted the log writer. */
    while (*message) sheng_panel_putc((unsigned char)*message++);
}

static void sheng_exception_hex(const char *name, uint64_t value)
{
    sheng_exception_text(name);
    for (unsigned n = 0; n < 16; n++) {
        const unsigned digit = (unsigned)((value >> ((15 - n) * 4)) & 15);
        sheng_panel_putc((unsigned char)(digit < 10 ? '0' + digit : 'A' + digit - 10));
    }
    sheng_panel_putc('\n');
}

void sheng_log_exception(uint64_t pc, uint64_t esr, uint64_t far, uint64_t sp)
{
    if (!sheng_panel_ready) return;
    if (sheng_status_pinned) {
        /* Native panic clearing may erase the title; restore the summary without replacing the first snapshot. */
        sheng_status_render("", sheng_status_message);
        return;
    }
    if (__atomic_exchange_n(&sheng_first_sync_displayed, 1, __ATOMIC_RELAXED)) return;
    sheng_status_pinned = 2;
    sheng_status_render("SYNC: ", "first EL1 sync - registers below");
    sheng_panel_reset();
    sheng_exception_hex("ELR=", pc);
    sheng_exception_hex("ESR=", esr);
    sheng_exception_hex("FAR=", far);
    sheng_exception_hex("SP =", sp);
    sheng_panel_pin_panic();
}

void sheng_log_stage(const char *message)
{
    if (message) {
        const char expected[] = "PE_lockdown_iokit";
        unsigned n = 0;
        while (n < sizeof(expected) - 1 && message[n] == expected[n]) n++;
        if (n == sizeof(expected) - 1 && !message[n]) sheng_boot_checkpoint(2);
    }
    sheng_log_status(message);
    const char *prefix = "\nSHENG: ";
    while (*prefix) sheng_log_putc(*prefix++);
    for (unsigned n = 0; message && message[n] && n < 160; n++) sheng_log_putc(message[n]);
    sheng_log_putc('\n');
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
    /* An earlier recoverable fault may occupy the RAM header; still pin the first actual panic on screen. */
    sheng_status_panic(message);
    uint64_t text_expected = 0;
    if (__atomic_compare_exchange_n(&sheng_panic_text_state, &text_expected, 1, 0,
        __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) {
        sheng_panic_writer_busy = __atomic_load_n(&r->writer, __ATOMIC_RELAXED);
        unsigned n = 0;
        for (; message && message[n] && n < sizeof(sheng_first_panic_text) - 1; n++)
            sheng_first_panic_text[n] = message[n];
        sheng_first_panic_text[n] = 0;
        sheng_log_clean(sheng_first_panic_text, sizeof(sheng_first_panic_text));
        __atomic_store_n(&sheng_panic_text_state, 2, __ATOMIC_RELEASE);
        sheng_log_clean(&sheng_panic_text_state, sizeof(sheng_panic_text_state));
        sheng_panic_panel_render();
    }
    {
        const char *prefix = "\nSHENG-LOG: panic: ";
        while (*prefix) sheng_log_putc(*prefix++);
        for (unsigned n = 0; message && message[n] && n < 4095; n++)
            sheng_log_putc(message[n]);
        sheng_log_putc('\n');
    }
    sheng_log_clean(r, sizeof(*r));
}
#endif
