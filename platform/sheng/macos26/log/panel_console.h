/* SPDX-License-Identifier: MIT */
/* 使用XNU原字体，写屏只在保留日志的writer作用域内进行 */
#define iso_font sheng_panel_font
#include "pe_sheng_font.h"
#undef iso_font

volatile uint64_t sheng_panel_ready, sheng_panel_characters, sheng_panel_witness;
volatile uint64_t sheng_status_witness;
char sheng_status_message[45];
static unsigned sheng_status_pinned;

/* 复用已验证的12行原生映射，单启动核状态输出不依赖日志writer */
static void sheng_status_render(const char *prefix, const char *message)
{
    const uintptr_t base = sheng_bootstrap_vm_pixels;
    const uintptr_t stride = sheng_bootstrap_vm_stride;
    if (!base || stride < 2560 || stride > 65536) return;
    unsigned length = 0;
    while (prefix && *prefix && length < 44) sheng_status_message[length++] = *prefix++;
    while (message && *message && length < 44) {
        const unsigned char c = (unsigned char)*message++;
        if (c >= 32 && c <= 126) sheng_status_message[length++] = (char)c;
    }
    sheng_status_message[length] = 0;
    uintptr_t white = 0;
    for (unsigned row = 0; row < 12; row++) {
        volatile uint32_t *pixels = (volatile uint32_t *)(base + row * stride);
        for (unsigned col = 0; col < 44; col++) {
            const unsigned bits = col < length ?
                sheng_panel_font[(unsigned char)sheng_status_message[col] * 16 + row * 16 / 12] : 0;
            for (unsigned x = 0; x < 8; x++) {
                const uint32_t color = bits & (1u << x) ? 0xffffffffu : 0xff000000u;
                pixels[col * 8 + x] = color;
                if (!white && color == 0xffffffffu) white = (uintptr_t)&pixels[col * 8 + x];
            }
        }
    }
    __asm__ volatile ("dsb sy" ::: "memory");
    if (white && *(volatile uint32_t *)white == 0xffffffffu) sheng_status_witness = 1;
}

void sheng_log_status(const char *message)
{
    if (!sheng_status_pinned) sheng_status_render("SHENG: ", message);
}

static void sheng_status_panic(const char *message)
{
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
    if (++sheng_panel.y == sheng_panel.rows) sheng_panel.y = sheng_panel.pinned;
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
