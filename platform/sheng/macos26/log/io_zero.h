/* SPDX-License-Identifier: MIT */
#ifndef SHENG_IO_ZERO_H
#define SHENG_IO_ZERO_H
#include <stddef.h>
#include <stdint.h>

/* panic区域可能是Device映射，显式访问不能被合并为DC ZVA或SIMD */
static void sheng_zero_panic_region(volatile void *address, size_t length)
{
    volatile uint8_t *cursor = address;
    while (length && ((uintptr_t)cursor & 3)) {
        *cursor++ = 0;
        length--;
    }
    while (length >= sizeof(uint32_t)) {
        *(volatile uint32_t *)cursor = 0;
        cursor += sizeof(uint32_t);
        length -= sizeof(uint32_t);
    }
    while (length--) *cursor++ = 0;
#if defined(__aarch64__)
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}
#endif
