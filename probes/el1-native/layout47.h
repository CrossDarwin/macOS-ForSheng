// SPDX-License-Identifier: MIT
#ifndef SHENG_LAYOUT47_H
#define SHENG_LAYOUT47_H

#define SHENG47_LOW  0xffff800000004000
#define SHENG47_CODE 0xfffffe0007004000
#define SHENG47_DATA 0xfffffe0009008000
#define SHENG47_HOLE 0xfffffe000b008000

#ifndef __ASSEMBLER__
typedef __UINT64_TYPE__ sheng47_u64;
#define SHENG47_BYTES (8 * 16384)

// 仅使用独占的8页：L1、两套L2、三套L3、代码和数据
static inline void
sheng47_tables(sheng47_u64 *pages, unsigned attribute)
{
    for (unsigned i = 0; i < SHENG47_BYTES / 8; i++) {
        pages[i] = 0;
    }
    sheng47_u64 base = (sheng47_u64)pages;
    sheng47_u64 *low_l2 = pages + 2048;
    sheng47_u64 *low_l3 = pages + 4096;
    sheng47_u64 *high_l2 = pages + 6144;
    sheng47_u64 *code_l3 = pages + 8192;
    sheng47_u64 *data_l3 = pages + 10240;
    const sheng47_u64 code = base + 6 * 16384;
    const sheng47_u64 data = base + 7 * 16384;
    const sheng47_u64 attr = (sheng47_u64)attribute << 2;
    pages[(SHENG47_LOW >> 36) & 2047] = (base + 16384) | 3;
    pages[(SHENG47_CODE >> 36) & 2047] = (base + 3 * 16384) | 3;
    low_l2[(SHENG47_LOW >> 25) & 2047] = (base + 2 * 16384) | 3;
    high_l2[(SHENG47_CODE >> 25) & 2047] = (base + 4 * 16384) | 3;
    high_l2[(SHENG47_DATA >> 25) & 2047] = (base + 5 * 16384) | 3;
    // 代码为EL1只读可执行，数据为EL1可写且禁止执行
    const sheng47_u64 rx = code | 0x783 | attr | (1ULL << 54);
    low_l3[(SHENG47_LOW >> 14) & 2047] = rx;
    code_l3[(SHENG47_CODE >> 14) & 2047] = rx;
    data_l3[(SHENG47_DATA >> 14) & 2047] = data | 0x703 | attr | (3ULL << 53);
}

static inline sheng47_u64
sheng47_tcr(sheng47_u64 firmware)
{
    return (firmware & ~((3ULL << 30) | (3ULL << 28) | (3ULL << 26) |
                         (3ULL << 24) | (1ULL << 23) | (63ULL << 16))) |
           (1ULL << 30) | (3ULL << 28) | (1ULL << 26) | (1ULL << 24) | (17ULL << 16);
}

extern sheng47_u64 ShengEl1Layout47Probe(sheng47_u64 *, sheng47_u64 *, sheng47_u64,
                                       sheng47_u64, sheng47_u64);
extern void ShengEl1Layout47Code(void);
extern void ShengEl1Layout47CodeEnd(void);
extern void ShengEl1Layout47End(void);
#endif
#endif
