/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "pe_sheng_log.h"
volatile uint32_t armcpu_smp_running, armcpu_smp_requested;
volatile uint32_t armcpu_smp_step[8], armcpu_smp_fail[8];
volatile int32_t armcpu_smp_psci_rc[8];
volatile uint32_t armcpu_smp_mpidr[8], armcpu_smp_seen_mpidr[8];
volatile uint32_t armcpu_core_timer[8], armcpu_core_sgi[8];
volatile uint64_t armcpu_ipi_sent, armcpu_ipi_interrupts;
typedef struct { uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth; } Boot_Video;
typedef struct { Boot_Video Video; } boot_args;
#include "vm_trace.h"

volatile uint64_t panic_test_checks;
volatile uint64_t snapshot_test_checks;
volatile uint64_t writer_scope_test_checks;
volatile uint64_t scroll_bounds_test_checks;
static struct sheng_log_record snapshot;
static uint64_t progress_clock = 120;
uint64_t sheng_boot_progress_seconds(void) { return progress_clock; }
__attribute__((noinline)) void progress_ready(void) { __asm__ volatile("nop"); }
__attribute__((noinline)) void handoff_ready(void) { __asm__ volatile("nop"); }
/* The freestanding fixture supplies the kernel memcpy dependency. */
void *memcpy(void *destination, const void *source, size_t size)
{
    volatile unsigned char *out = destination;
    const volatile unsigned char *in = source;
    for (size_t i = 0; i < size; i++) out[i] = in[i];
    return destination;
}
__attribute__((noinline)) void panic_ready(void) { __asm__ volatile("nop"); }

void run_trace(void)
{
    boot_args args = { .Video = { .v_baseAddr = 0x44000000, .v_rowBytes = 12192,
        .v_width = 3048, .v_height = 2032, .v_depth = 32 } };
    args.Video.v_height = 800;
    sheng_vm_trace_begin(&args);
    if (sheng_console_rows == 6 && sheng_console_panic_rows == 16) panic_test_checks |= 8;
    args.Video.v_height = 2032;
    sheng_vm_trace_begin(&args);
    sheng_status_pixels = sheng_status_row_pa;
    sheng_log_bind_panel(sheng_status_pixels + 32 * sheng_status_scale * sheng_bootstrap_vm_stride,
        12192, 88, (unsigned)sheng_console_rows, 2);
    sheng_log_bind_panic_panel(sheng_status_pixels + (32 + 16 * sheng_console_rows) *
        sheng_status_scale * sheng_bootstrap_vm_stride, 12192, 88, (unsigned)sheng_console_panic_rows, 2);
    /* A busy progress scanline must never leave the scroll cursor outside its region. */
    const uintptr_t after_panel = sheng_panel.base + sheng_panel.rows * 16 *
        sheng_panel.scale * sheng_panel.stride;
    volatile uint32_t *guard = (volatile uint32_t *)after_panel;
    for (unsigned n = 0; n < 2 * sheng_panel.stride / 4; n++) guard[n] = 0x12345678;
    sheng_panel.y = sheng_panel.rows - 1;
    sheng_framebuffer.writer = 1;
    sheng_panel_putc('\n');
    if (sheng_panel.y == sheng_panel.rows - 1) scroll_bounds_test_checks |= 1;
    sheng_framebuffer.writer = 0;
    sheng_panel_putc('X');
    sheng_panel_putc('\n');
    int guard_intact = 1;
    for (unsigned n = 0; n < 2 * sheng_panel.stride / 4; n++)
        if (guard[n] != 0x12345678) guard_intact = 0;
    if (guard_intact) scroll_bounds_test_checks |= 2;
    sheng_panel.y = sheng_panel.rows + 10;
    sheng_panel_putc('Y');
    if (sheng_panel.y == sheng_panel.rows - 1) scroll_bounds_test_checks |= 4;
    sheng_panel_clear_row(sheng_panel.rows);
    guard_intact = 1;
    for (unsigned n = 0; n < 2 * sheng_panel.stride / 4; n++)
        if (guard[n] != 0x12345678) guard_intact = 0;
    if (guard_intact) scroll_bounds_test_checks |= 8;
    sheng_panel_reset();
    uint64_t before_total = sheng_log_buffer.total, before_dropped = sheng_log_buffer.dropped;
    uint64_t before_pixels = sheng_panel_characters, original_daif, observed_daif;
    __asm__ volatile("mrs %0, daif\nmsr daifclr, #7" : "=r"(original_daif) :: "memory");
    sheng_log_panel_writer = 1;
    sheng_log_putc('R');
    __asm__ volatile("mrs %0, daif" : "=r"(observed_daif));
    if (sheng_log_buffer.total == before_total + 1 && sheng_log_buffer.dropped == before_dropped &&
        sheng_panel_characters == before_pixels && !sheng_log_buffer.writer &&
        sheng_log_buffer.tail[before_total % SHENG_LOG_TAIL] == 'R') writer_scope_test_checks |= 1;
    if (sheng_log_snapshot_copy(&snapshot, sizeof(snapshot)) == sizeof(snapshot) &&
        snapshot.total == before_total + 1 && !snapshot.writer) writer_scope_test_checks |= 2;
    uint64_t after_snapshot;
    __asm__ volatile("mrs %0, daif\nmsr daif, %1" : "=&r"(after_snapshot) : "r"(original_daif) : "memory");
    if (observed_daif == (original_daif & ~0x1c0ULL) && after_snapshot == observed_daif)
        writer_scope_test_checks |= 4;
    sheng_log_panel_writer = 0;
    sheng_boot_progress_enabled = 1;
    for (unsigned stage = 0; stage < 4; stage++) sheng_boot_checkpoint(stage);
    sheng_boot_service("launchd", 1, 0, 0);
    sheng_boot_service("WindowServer", 85, 0, 0);
    progress_clock = 180;
    sheng_boot_progress_tick();
    progress_ready();
    sheng_panel_ready = 0;
    progress_clock = 240;
    sheng_boot_progress_tick();
    handoff_ready();
    sheng_panel_ready = 1;
    sheng_log_stage("ordinary log before interrupted writer");
    char reason[4096];
    const char first[] = "UFS ROOT FAILURE: root window volume not found\nstage=media publication prepared=1 published=1 reads=42 failures=0\n"
        "media disk0 bytes=5e000000 uuid=-\nmedia disk0s1 bytes=5df00000 uuid=808EAC5E-8275-478D-814C-2229D8EB8D07\n";
    unsigned at = 0;
    for (unsigned n = 0; n < sizeof(first) - 1; n++) reason[at++] = first[n];
    while (at < 3900) { reason[at] = at % 79 == 0 ? '\n' : 'x'; at++; }
    const char end[] = "PAYLOAD_END_AFTER_511_BYTES\n";
    for (unsigned n = 0; n < sizeof(end); n++) reason[at++] = end[n];
    /* Simulate a recoverable fault occupying the RAM header and a normal writer interrupted before panic. */
    sheng_log_buffer.panic_state = 3;
    sheng_log_buffer.writer = 1;
    sheng_log_panel_writer = 1;
    if (!sheng_log_snapshot_copy(&snapshot, sizeof(snapshot)) && sheng_log_buffer.writer == 1)
        snapshot_test_checks |= 1;
    /* A fault may interrupt a GUI scanline while its lease is still held. */
    sheng_framebuffer.owner = SHENG_FB_GUI;
    sheng_framebuffer.writer = 1;
    sheng_log_panic(0x112233, reason);
    /* Simulate the last in-flight scanline completing after the immediate panic draw. */
    volatile uint32_t *panic_pixel = (volatile uint32_t *)sheng_panic_panel.base;
    *panic_pixel = 0x12345678;
    sheng_framebuffer.writer = 0;
    sheng_log_panic_redraw();
    uint64_t lease;
    if (*panic_pixel == 0xff000000 && !sheng_fb_begin(SHENG_FB_GUI, &lease) &&
        !sheng_fb_claim_gui()) writer_scope_test_checks |= 8;
    sheng_fb_abort_gui();
    if (sheng_framebuffer.owner == SHENG_FB_PANIC) writer_scope_test_checks |= 16;
    if (sheng_log_buffer.writer == 1 && sheng_log_buffer.panic_state == 3 &&
        sheng_panic_text_state == 2 && sheng_panic_writer_busy == 1 && sheng_log_buffer.dropped > 0)
        panic_test_checks |= 1;
    for (unsigned n = 0; n < at; n++) {
        if (sheng_first_panic_text[n] != reason[n]) break;
        if (n + 1 == at) panic_test_checks |= 2;
    }
    panic_ready();
    /* A resumed interrupted writer may touch only the normal pixel region. */
    sheng_log_buffer.writer = 0;
    sheng_log_panel_writer = 0;
    for (unsigned n = 0; n < 80; n++) sheng_log_stage("ordinary log after first panic");
    sheng_log_panic(0x998877, "SECOND PANIC MUST NOT REPLACE FIRST");
    if (sheng_panic_writer_busy == 1 && sheng_first_panic_text[0] == 'U') panic_test_checks |= 4;
    if (sheng_log_snapshot_copy(&snapshot, sizeof(snapshot)) == sizeof(snapshot) &&
        !snapshot.writer && !sheng_log_buffer.writer && snapshot.total == sheng_log_buffer.total &&
        snapshot.panic_state == sheng_log_buffer.panic_state) snapshot_test_checks |= 2;
    if (!sheng_log_snapshot_copy(0, sizeof(snapshot)) &&
        !sheng_log_snapshot_copy(&snapshot, sizeof(snapshot)-1) && !sheng_log_buffer.writer)
        snapshot_test_checks |= 4;
}
