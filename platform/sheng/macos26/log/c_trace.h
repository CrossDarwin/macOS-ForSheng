/* SPDX-License-Identifier: MIT */
/* 只在arm_vm_init替换启动页表前使用，不依赖函数指针、锁或控制台 */
extern uint64_t sheng_bootstrap_fb_trace_ready;
extern volatile uint64_t sheng_bootstrap_c_stage;

static __attribute__((always_inline)) inline void
sheng_bootstrap_c_trace(const boot_args *args, unsigned stage)
{
    sheng_bootstrap_c_stage = stage;
    __asm__ volatile ("dsb sy" ::: "memory");
    if (!sheng_bootstrap_fb_trace_ready || stage > 15) {
        return;
    }
    const Boot_Video *video = &args->Video;
    const uintptr_t base = video->v_baseAddr;
    const uintptr_t stride = video->v_rowBytes;
    if (!base || video->v_width < 640 || video->v_height < 640 ||
        (video->v_depth & 255) != 32 || stride < 2560 || stride > 65536) {
        return;
    }
    /* 沿用已映射的同一行，青色表示C阶段，灰色表示该阶段尚未完成 */
    for (unsigned cell = 0; cell < 16; cell++) {
        if (stage != 0 && cell != stage) {
            continue;
        }
        const uint32_t color = cell == stage ? 0xff00ffffu : 0xff404040u;
        for (unsigned row = 568; row < 580; row++) {
            volatile uint32_t *pixel = (volatile uint32_t *)(base + row * stride +
                (224 + cell * 24) * sizeof(uint32_t));
            for (unsigned col = 0; col < 5; col++) {
                pixel[col] = color;
            }
        }
    }
    __asm__ volatile ("dsb sy" ::: "memory");
}
