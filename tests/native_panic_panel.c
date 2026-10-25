/* SPDX-License-Identifier: MIT */
#include "pe_sheng_log.h"
typedef struct { uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth; } Boot_Video;
typedef struct { Boot_Video Video; } boot_args;
#include "vm_trace.h"

volatile uint64_t panic_test_checks;
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
    sheng_log_stage("ordinary log before interrupted writer");
    char reason[4096];
    const char first[] = "UFS ROOT FAILURE: root window volume not found\nstage=media publication prepared=1 published=1 reads=42 failures=0\n"
        "media disk0 bytes=5e000000 uuid=-\nmedia disk0s1 bytes=5df00000 uuid=808EAC5E-8275-478D-814C-2229D8EB8D07\n";
    unsigned at = 0;
    for (unsigned n = 0; n < sizeof(first) - 1; n++) reason[at++] = first[n];
    while (at < 3900) { reason[at] = at % 79 == 0 ? '\n' : 'x'; at++; }
    const char end[] = "PAYLOAD_END_AFTER_511_BYTES\n";
    for (unsigned n = 0; n < sizeof(end); n++) reason[at++] = end[n];
    /* 模拟可恢复异常已占用RAM头，普通writer在panic前被打断 */
    sheng_log_buffer.panic_state = 3;
    sheng_log_buffer.writer = 1;
    sheng_log_panic(0x112233, reason);
    if (sheng_log_buffer.writer == 1 && sheng_log_buffer.panic_state == 3 &&
        sheng_panic_text_state == 2 && sheng_panic_writer_busy == 1 && sheng_log_buffer.dropped > 0)
        panic_test_checks |= 1;
    for (unsigned n = 0; n < at; n++) {
        if (sheng_first_panic_text[n] != reason[n]) break;
        if (n + 1 == at) panic_test_checks |= 2;
    }
    panic_ready();
    /* 被打断的writer恢复后只能使用普通像素区 */
    sheng_log_buffer.writer = 0;
    for (unsigned n = 0; n < 80; n++) sheng_log_stage("ordinary log after first panic");
    sheng_log_panic(0x998877, "SECOND PANIC MUST NOT REPLACE FIRST");
    if (sheng_panic_writer_busy == 1 && sheng_first_panic_text[0] == 'U') panic_test_checks |= 4;
}
