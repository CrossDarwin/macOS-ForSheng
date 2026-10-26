/* SPDX-License-Identifier: MIT */
#ifndef SHENG_PANIC_QR_H
#define SHENG_PANIC_QR_H
#include "pe_sheng_qr_encoder.h"
#define SHENG_QR_PAYLOAD_MAX 640u
#define SHENG_QR_REASON_MAX 256u
#define SHENG_QR_VERSION_MAX 20
struct sheng_panic_qr_capture {
    uint64_t caller, sp, elr, esr, far;
    uint64_t physical_base, image_va, total, dropped;
    uint8_t uuid[16];
};
static uint8_t sheng_qr_scratch[qrcodegen_BUFFER_LEN_FOR_VERSION(SHENG_QR_VERSION_MAX)];
static uint8_t sheng_qr_modules[qrcodegen_BUFFER_LEN_FOR_VERSION(SHENG_QR_VERSION_MAX)];
static char sheng_qr_payload[SHENG_QR_PAYLOAD_MAX];
static uint32_t sheng_qr_state;
static unsigned sheng_qr_payload_bytes;
static struct sheng_panic_qr_capture sheng_qr_capture;

static void sheng_qr_append(unsigned *used, const char *text)
{
    while (*text && *used + 1 < SHENG_QR_PAYLOAD_MAX) sheng_qr_payload[(*used)++] = *text++;
    sheng_qr_payload[*used] = 0;
}
static void sheng_qr_hex(unsigned *used, uint64_t value, unsigned digits)
{
    static const char hex[] = "0123456789ABCDEF";
    for (unsigned i = digits; i && *used + 1 < SHENG_QR_PAYLOAD_MAX; i--)
        sheng_qr_payload[(*used)++] = hex[(value >> ((i - 1) * 4)) & 15];
    sheng_qr_payload[*used] = 0;
}
/* Only the first panic owns these static buffers; recursion returns without waiting. */
static int sheng_qr_prepare(const struct sheng_panic_qr_capture *capture, const char *reason)
{
    uint32_t expected = 0;
    if (!__atomic_compare_exchange_n(&sheng_qr_state, &expected, 1, 0,
        __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) return 0;
    sheng_qr_capture = *capture;
    unsigned used = 0;
    sheng_qr_append(&used, "SHENG-PANIC-1\nUUID=");
    for (unsigned i = 0; i < 16; i++) {
        if (i == 4 || i == 6 || i == 8 || i == 10) sheng_qr_append(&used, "-");
        sheng_qr_hex(&used, capture->uuid[i], 2);
    }
    const char *keys[] = {"\nCALLER=", "\nSP=", "\nELR=", "\nESR=", "\nFAR=",
        "\nPHYS=", "\nIMAGE=", "\nTOTAL=", "\nDROPPED="};
    const uint64_t values[] = {capture->caller, capture->sp, capture->elr, capture->esr,
        capture->far, capture->physical_base, capture->image_va, capture->total, capture->dropped};
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); i++) {
        sheng_qr_append(&used, keys[i]);
        sheng_qr_hex(&used, values[i], 16);
    }
    sheng_qr_append(&used, "\nREGS=panic-hook\nREASON=");
    unsigned n = 0;
    for (; reason && reason[n] && n < SHENG_QR_REASON_MAX; n++) {
        const unsigned char c = (unsigned char)reason[n];
        char value[] = {(char)(c >= 32 && c <= 126 ? c : ' '), 0};
        sheng_qr_append(&used, value);
    }
    sheng_qr_append(&used, reason && reason[n] ? "\nTRUNCATED=1" : "\nTRUNCATED=0");
    sheng_qr_payload_bytes = used;
    for (unsigned i = 0; i < used; i++) sheng_qr_scratch[i] = (uint8_t)sheng_qr_payload[i];
    int success = qrcodegen_encodeBinary(sheng_qr_scratch, used, sheng_qr_modules,
        qrcodegen_Ecc_MEDIUM, 1, SHENG_QR_VERSION_MAX, qrcodegen_Mask_AUTO, false);
    __atomic_store_n(&sheng_qr_state, success ? 2 : 3, __ATOMIC_RELEASE);
    return success;
}

/* Fit the QR and its four-module quiet zone inside the already mapped panic region. */
static unsigned sheng_qr_extent(unsigned width, unsigned height, unsigned *scale)
{
    if (__atomic_load_n(&sheng_qr_state, __ATOMIC_ACQUIRE) != 2) return 0;
    unsigned modules = (unsigned)qrcodegen_getSize(sheng_qr_modules) + 8;
    unsigned limit = height < width / 2 ? height : width / 2;
    *scale = limit / modules;
    if (*scale > 6) *scale = 6;
    return *scale >= 2 ? modules * *scale : 0;
}
static void sheng_qr_draw(uintptr_t base, unsigned stride, unsigned width, unsigned height)
{
    unsigned scale = 0, extent = sheng_qr_extent(width, height, &scale);
    if (!extent) return;
    unsigned size = (unsigned)qrcodegen_getSize(sheng_qr_modules);
    for (unsigned y = 0; y < extent; y++) {
        volatile uint32_t *pixels = (volatile uint32_t *)(base + y * stride + (width - extent) * 4);
        for (unsigned x = 0; x < extent; x++) {
            unsigned mx = x / scale, my = y / scale;
            int dark = mx >= 4 && my >= 4 && mx < size + 4 && my < size + 4 &&
                qrcodegen_getModule(sheng_qr_modules, (int)mx - 4, (int)my - 4);
            pixels[x] = dark ? 0xff000000u : 0xffffffffu;
        }
    }
    __asm__ volatile("dsb sy" ::: "memory");
}
#endif
