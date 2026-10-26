/* SPDX-License-Identifier: MIT */
/* Panic encoding uses only bounded caller-owned buffers and byte accesses. */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
static void *sheng_qr_memset(void *destination, int value, size_t count)
{
    volatile uint8_t *out = destination;
    for (size_t i = 0; i < count; i++) out[i] = (uint8_t)value;
    return destination;
}
static void *sheng_qr_memcpy(void *destination, const void *source, size_t count)
{
    volatile uint8_t *out = destination;
    const volatile uint8_t *in = source;
    for (size_t i = 0; i < count; i++) out[i] = in[i];
    return destination;
}
static void *sheng_qr_memmove(void *destination, const void *source, size_t count)
{
    volatile uint8_t *out = destination;
    const volatile uint8_t *in = source;
    if ((uintptr_t)out > (uintptr_t)in) {
        for (size_t i = count; i; i--) out[i - 1] = in[i - 1];
    } else {
        for (size_t i = 0; i < count; i++) out[i] = in[i];
    }
    return destination;
}
static size_t sheng_qr_strlen(const char *text)
{
    size_t count = 0;
    while (text[count]) count++;
    return count;
}
static const char *sheng_qr_strchr(const char *text, int character)
{
    do {
        if ((unsigned char)*text == (unsigned char)character) return text;
    } while (*text++);
    return NULL;
}
