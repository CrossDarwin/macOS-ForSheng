/* SPDX-License-Identifier: MIT */
#ifndef SHENG_IO_ZERO_H
#define SHENG_IO_ZERO_H
#include <stddef.h>
#include <stdint.h>

/* The panic region may use a Device mapping; prevent explicit stores from becoming DC ZVA or SIMD. */
static void sheng_zero_panic_region(volatile void *address, size_t length)
{
    volatile uint8_t *cursor = address;
    while (length && ((uintptr_t)cursor & 3)) {
        *cursor++ = 0;
        length--;
    }
    volatile void *aligned = cursor;
    volatile uint32_t *words = aligned;
    while (length >= sizeof(uint32_t)) {
        *words++ = 0;
        length -= sizeof(uint32_t);
    }
    cursor = (volatile uint8_t *)words;
    while (length--) *cursor++ = 0;
#if defined(__aarch64__)
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}
#endif
