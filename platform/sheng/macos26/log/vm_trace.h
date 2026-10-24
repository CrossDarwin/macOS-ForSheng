/* SPDX-License-Identifier: MIT */
#ifndef SHENG_VM_TRACE_H
#define SHENG_VM_TRACE_H
extern uint64_t sheng_bootstrap_fb_trace_ready;
extern volatile uint64_t sheng_bootstrap_vm_stage;
extern volatile uint64_t sheng_bootstrap_vm_pixels;
extern uint64_t sheng_bootstrap_vm_row_pa, sheng_bootstrap_vm_stride;
extern volatile uint64_t sheng_bootstrap_vm_witness;

static __attribute__((always_inline)) inline void
sheng_vm_trace(unsigned stage)
{
    sheng_bootstrap_vm_stage = stage;
    __asm__ volatile ("dsb sy" ::: "memory");
    const uintptr_t base = sheng_bootstrap_vm_pixels;
    const uintptr_t stride = sheng_bootstrap_vm_stride;
    if (!base || stage > 15) {
        return;
    }
    for (unsigned cell = 0; cell < 16; cell++) {
        const uint32_t color = cell <= stage ? 0xffff00ffu : 0xff404040u;
        for (unsigned row = 0; row < 12; row++) {
            volatile uint32_t *pixel = (volatile uint32_t *)(base + row * stride + cell * 96);
            for (unsigned col = 0; col < 5; col++) {
                pixel[col] = color;
            }
        }
    }
    __asm__ volatile ("dsb sy" ::: "memory");
    if (*(volatile uint32_t *)(base + stage * 96) == 0xffff00ffu) {
        sheng_bootstrap_vm_witness |= 1ull << stage;
    }
}

static __attribute__((always_inline)) inline void
sheng_vm_trace_begin(const boot_args *args)
{
    const Boot_Video *video = &args->Video;
    const uint64_t stride = video->v_rowBytes;
    sheng_bootstrap_vm_pixels = 0;
    sheng_bootstrap_vm_row_pa = 0;
    sheng_bootstrap_vm_witness = 0;
    if (video->v_baseAddr && video->v_width >= 640 && video->v_height >= 580 &&
        video->v_height <= 16384 && (video->v_depth & 255) == 32 &&
        stride >= 2560 && stride <= 65536 && video->v_width <= stride / 4) {
        const uint64_t first = video->v_baseAddr + 568 * stride + 896;
        const uint64_t end = first + 11 * stride + 1460;
        if (first >= video->v_baseAddr && end > first && end < (1ull << 47)) {
            sheng_bootstrap_vm_row_pa = first;
            sheng_bootstrap_vm_stride = stride;
            if (sheng_bootstrap_fb_trace_ready) {
                sheng_bootstrap_vm_pixels = first;
            }
        }
    }
    sheng_vm_trace(0);
}

static __attribute__((always_inline)) inline void
sheng_vm_trace_drop_identity(void)
{
    sheng_vm_trace(7);
    /* 先停用物理写屏，再让原生VM撤销TTBR0，不延长identity映射寿命 */
    sheng_bootstrap_vm_pixels = 0;
    __asm__ volatile ("dsb sy" ::: "memory");
}
#endif
