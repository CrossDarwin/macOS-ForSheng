/* SPDX-License-Identifier: MIT */
/* 复用XNU原字体，启动摘要独立于保留日志writer */
#define iso_font sheng_panel_font
#include "pe_sheng_font.h"
#undef iso_font

volatile uint64_t sheng_panel_ready, sheng_panel_characters, sheng_panel_witness;
volatile uint64_t sheng_status_witness;
char sheng_status_message[45];
static unsigned sheng_status_pinned;

volatile uint64_t sheng_status_pixels;
uint64_t sheng_status_row_pa, sheng_status_scale, sheng_console_columns, sheng_console_rows;
uint64_t sheng_console_panic_rows;
volatile uint64_t sheng_panic_panel_bound_rows, sheng_panic_text_state, sheng_panic_writer_busy;
char sheng_first_panic_text[4096];
static struct {
    uintptr_t base;
    unsigned stride, columns, rows, scale;
} sheng_panic_panel;

/* 独占像素区和游标，不等待可能被panic打断的普通日志writer */
static void sheng_panic_panel_render(void)
{
    if (!sheng_panic_panel.base ||
        __atomic_load_n(&sheng_panic_text_state, __ATOMIC_ACQUIRE) != 2) return;
    const unsigned scale = sheng_panic_panel.scale;
    for (unsigned y = 0; y < sheng_panic_panel.rows * 16 * scale; y++) {
        volatile uint32_t *pixels = (volatile uint32_t *)(sheng_panic_panel.base +
            y * sheng_panic_panel.stride);
        for (unsigned x = 0; x < sheng_panic_panel.columns * 8 * scale; x++) pixels[x] = 0xff000000u;
    }
    unsigned row = 0, column = 0;
    for (unsigned part = 0; part < 2; part++) {
        const char *text = part ? sheng_first_panic_text : "SHENG - PANIC DETAIL\n";
        for (unsigned n = 0; text[n] && n < 4095 && row < sheng_panic_panel.rows; n++) {
            const unsigned char c = (unsigned char)text[n];
            if (c == '\r') { column = 0; continue; }
            if (c == '\n') { column = 0; row++; continue; }
            if (c < 32 || c > 126) continue;
            const uintptr_t origin = sheng_panic_panel.base +
                row * 16 * scale * sheng_panic_panel.stride + column * 8 * scale * 4;
            for (unsigned y = 0; y < 16 * scale; y++) {
                volatile uint32_t *pixels = (volatile uint32_t *)(origin + y * sheng_panic_panel.stride);
                const unsigned bits = sheng_panel_font[c * 16 + y / scale];
                for (unsigned x = 0; x < 8 * scale; x++)
                    pixels[x] = bits & (1u << (x / scale)) ? 0xffffffffu : 0xff000000u;
            }
            if (++column == sheng_panic_panel.columns) { column = 0; row++; }
        }
    }
    __asm__ volatile ("dsb sy" ::: "memory");
}

/* 同一次原生映射覆盖独立文字区，旧阶段条不再与文字共用像素 */
static void sheng_status_render(const char *prefix, const char *message)
{
    const uintptr_t base = sheng_status_pixels;
    const uintptr_t stride = sheng_bootstrap_vm_stride;
    const unsigned scale = (unsigned)sheng_status_scale;
    if (!base || stride < 2560 || stride > 65536 || (scale != 1 && scale != 2)) return;
    unsigned length = 0;
    while (prefix && *prefix && length < 44) sheng_status_message[length++] = *prefix++;
    while (message && *message && length < 44) {
        const unsigned char c = (unsigned char)*message++;
        if (c >= 32 && c <= 126) sheng_status_message[length++] = (char)c;
    }
    sheng_status_message[length] = 0;
    uintptr_t white = 0;
    for (unsigned line = 0; line < 2; line++) {
        const char *text = line ? sheng_status_message :
            (sheng_status_pinned == 2 ? "SHENG - FIRST EL1 SYNC" :
             sheng_status_pinned ? "SHENG - FIRST PANIC" : "SHENG - BOOT LOG");
        unsigned col = 0;
        for (; col < 44; col++) {
            const unsigned char c = *text ? (unsigned char)*text++ : ' ';
            for (unsigned row = 0; row < 16; row++) {
                const unsigned bits = sheng_panel_font[c * 16 + row];
                for (unsigned y = 0; y < scale; y++) {
                    volatile uint32_t *pixels = (volatile uint32_t *)(base +
                        ((line * 16 + row) * scale + y) * stride + col * 8 * scale * 4);
                    for (unsigned x = 0; x < 8; x++) {
                        const uint32_t color = bits & (1u << x) ? 0xffffffffu : 0xff000000u;
                        for (unsigned sx = 0; sx < scale; sx++) pixels[x * scale + sx] = color;
                        if (!white && color == 0xffffffffu) white = (uintptr_t)&pixels[x * scale];
                    }
                }
            }
        }
    }
    __asm__ volatile ("dsb sy" ::: "memory");
    if (white && *(volatile uint32_t *)white == 0xffffffffu) sheng_status_witness = 1;
}

void sheng_log_status(const char *message)
{
    if (sheng_status_pinned) sheng_status_render("", sheng_status_message);
    else sheng_status_render("SHENG: ", message);
}

static void sheng_status_panic(const char *message)
{
    if (sheng_status_pinned) return;
    sheng_status_pinned = 1;
    sheng_status_render("PANIC: ", message);
}

static struct {
    uintptr_t base;
    unsigned stride, columns, rows, scale, x, y, pinned;
} sheng_panel;

static void sheng_panel_clear_row(unsigned row)
{
    for (unsigned y = 0; y < 16 * sheng_panel.scale; y++) {
        volatile uint32_t *p = (volatile uint32_t *)(sheng_panel.base +
            (row * 16 * sheng_panel.scale + y) * sheng_panel.stride);
        for (unsigned x = 0; x < sheng_panel.columns * 8 * sheng_panel.scale; x++) {
            p[x] = 0xff000000u;
        }
    }
}

static void sheng_panel_reset(void)
{
    sheng_panel.x = sheng_panel.y = sheng_panel.pinned = 0;
    if (!sheng_panel_ready) return;
    for (unsigned row = 0; row < sheng_panel.rows; row++) sheng_panel_clear_row(row);
}

static void sheng_panel_newline(void)
{
    sheng_panel.x = 0;
    if (++sheng_panel.y == sheng_panel.rows) {
        /* I/O映射逐字访问，不调用可能使用SIMD或DC ZVA的内存例程 */
        const unsigned pixels = sheng_panel.columns * 8 * sheng_panel.scale;
        for (unsigned row = sheng_panel.pinned; row + 1 < sheng_panel.rows; row++) {
            for (unsigned y = 0; y < 16 * sheng_panel.scale; y++) {
                volatile uint32_t *dst = (volatile uint32_t *)(sheng_panel.base +
                    (row * 16 * sheng_panel.scale + y) * sheng_panel.stride);
                volatile uint32_t *src = (volatile uint32_t *)((uintptr_t)dst +
                    16 * sheng_panel.scale * sheng_panel.stride);
                for (unsigned x = 0; x < pixels; x++) dst[x] = src[x];
            }
        }
        sheng_panel.y = sheng_panel.rows - 1;
    }
    sheng_panel_clear_row(sheng_panel.y);
}

static void sheng_panel_putc(unsigned char byte)
{
    if (!sheng_panel_ready) return;
    if (byte == '\r') { sheng_panel.x = 0; return; }
    if (byte == '\n') { sheng_panel_newline(); return; }
    if (byte < 32 || byte > 126) return;
    const unsigned scale = sheng_panel.scale;
    const uintptr_t origin = sheng_panel.base + sheng_panel.y * 16 * scale * sheng_panel.stride +
        sheng_panel.x * 8 * scale * sizeof(uint32_t);
    uintptr_t white = 0;
    for (unsigned row = 0; row < 16; row++) {
        const unsigned bits = sheng_panel_font[byte * 16 + row];
        for (unsigned y = 0; y < scale; y++) {
            volatile uint32_t *p = (volatile uint32_t *)(origin + (row * scale + y) * sheng_panel.stride);
            for (unsigned col = 0; col < 8; col++) {
                const uint32_t color = bits & (1u << col) ? 0xffffffffu : 0xff000000u;
                for (unsigned x = 0; x < scale; x++) p[col * scale + x] = color;
                if (!white && color == 0xffffffffu) white = (uintptr_t)&p[col * scale];
            }
        }
    }
    __asm__ volatile ("dsb sy" ::: "memory");
    if (white && *(volatile uint32_t *)white == 0xffffffffu) sheng_panel_witness = 1;
    sheng_panel_characters++;
    if (++sheng_panel.x == sheng_panel.columns) sheng_panel_newline();
}

static void sheng_panel_pin_panic(void)
{
    if (!sheng_panel_ready) return;
    sheng_panel.pinned = sheng_panel.y + 1;
    if (sheng_panel.pinned > sheng_panel.rows - 2) sheng_panel.pinned = sheng_panel.rows - 2;
    sheng_panel.y = sheng_panel.pinned;
    sheng_panel.x = 0;
    sheng_panel_clear_row(sheng_panel.y);
}
