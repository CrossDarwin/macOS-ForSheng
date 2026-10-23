/* SPDX-License-Identifier: MIT */
/* 冷启动使用，MMU开启后的标记要求临时Device映射，x16-x18和NZCV为临时状态 */
#ifndef SHENG_EARLY_ADDRESS
#ifdef __APPLE__
#define SHENG_EARLY_ADDRESS(reg, name) adrp reg, name@page; add reg, reg, name@pageoff
#else
#define SHENG_EARLY_ADDRESS(reg, name) adrp reg, name; add reg, reg, :lo12:name
#endif
#endif
.macro SHENG_BOOTSTRAP_TRACE stage, color=0xff00ff00, record=1
#if SHENG
	cbnz x21, 9f
	.if \record
	mov x16, #\stage
	adr x17, EXT(sheng_early_exception_record)
	str x16, [x17, #184]
	.if \stage >= 13
	SHENG_EARLY_ADDRESS(x17, EXT(sheng_bootstrap_fb_trace_ready))
	ldr x16, [x17]
	cbz x16, 9f
	.endif
	.endif
	ldr x16, [x20, BA_VIDEO_BASE]
	cbz x16, 9f
	ldr x17, [x20, BA_VIDEO_WIDTH]
	cmp x17, #640
	b.lo 9f
	ldr x17, [x20, BA_VIDEO_HEIGHT]
	cmp x17, #640
	b.lo 9f
	ldr x17, [x20, BA_VIDEO_DEPTH]
	and x17, x17, #255
	cmp x17, #32
	b.ne 9f
	ldr x17, [x20, BA_VIDEO_ROW_BYTES]
	cmp x17, #2560
	b.lo 9f
	mov x18, #65536
	cmp x17, x18
	b.hi 9f
	mov x18, #568
	madd x16, x18, x17, x16
	add x16, x16, #(896 + 96 * \stage)
	mov x18, #(\color & 0xffff)
	movk x18, #((\color >> 16) & 0xffff), lsl #16
	movk x18, #(\color & 0xffff), lsl #32
	movk x18, #((\color >> 16) & 0xffff), lsl #48
	.rept 12
	stp x18, x18, [x16]
	str w18, [x16, #16]
	add x16, x16, x17
	.endr
	dsb sy
9:
#endif
.endmacro

/* 页表已建立但MMU仍关闭，只映射阶段条所在的至多两个32 MiB块 */
.macro SHENG_BOOTSTRAP_MAP_TRACE
#if SHENG
	cbnz x21, 9f
	SHENG_EARLY_ADDRESS(x8, EXT(sheng_bootstrap_fb_trace_ready))
	str xzr, [x8]
	ldr x0, [x20, BA_VIDEO_BASE]
	cbz x0, 9f
	ldr x1, [x20, BA_VIDEO_WIDTH]
	cmp x1, #640
	b.lo 9f
	ldr x1, [x20, BA_VIDEO_HEIGHT]
	cmp x1, #640
	b.lo 9f
	ldr x1, [x20, BA_VIDEO_DEPTH]
	and x1, x1, #255
	cmp x1, #32
	b.ne 9f
	ldr x1, [x20, BA_VIDEO_ROW_BYTES]
	cmp x1, #2560
	b.lo 9f
	mov x2, #65536
	cmp x1, x2
	b.hi 9f
	mov x2, #568
	madd x0, x1, x2, x0
	mov x2, #11
	madd x1, x1, x2, x0
	add x1, x1, #2415
	// 防止错误输入回绕或超出当前47位TTBR0窗口
	cmp x1, x0
	b.lo 9f
	lsr x2, x1, #47
	cbnz x2, 9f
	and x0, x0, #0xfffffffffe000000
	and x1, x1, #0xfffffffffe000000
	lsr x2, x0, #36
	lsr x3, x1, #36
	cmp x2, x3
	b.ne 9f
	add x2, x25, x2, lsl #3
	ldr x3, [x2]
	cbnz x3, 2f
	SHENG_EARLY_ADDRESS(x4, EXT(sheng_bootstrap_fb_l2))
	mov x5, x4
	mov x6, #2048
1:
	str xzr, [x5], #8
	subs x6, x6, #1
	b.ne 1b
	orr x3, x4, #3
	str x3, [x2]
	b 3f
2:
	and x4, x3, #3
	cmp x4, #3
	b.ne 9f
	and x4, x3, #0x0000ffffffffc000
	// 已有L2必须属于原生启动页表池，不能沿任意指针写入
	cmp x4, x25
	b.lo 9f
	add x5, x25, #(BOOTSTRAP_TABLE_BYTES >> 12), lsl #12
	cmp x4, x5
	b.hs 9f
3:
	ubfx x5, x0, #25, #11
	add x5, x4, x5, lsl #3
	ubfx x6, x1, #25, #11
	add x6, x4, x6, lsl #3
	// 先检查整个范围，不覆盖内核或已有映射
	ldr x7, [x5]
	cbnz x7, 9f
	ldr x7, [x6]
	cbnz x7, 9f
	// MAIR slot3为Device-nGnRnE，两级执行禁止，EL1可读写
	mov x7, #0x60d
	orr x7, x7, #0x0060000000000000
	orr x2, x0, x7
	str x2, [x5]
	orr x2, x1, x7
	str x2, [x6]
	mov x2, #1
	str x2, [x8]
	dsb sy
9:
	SHENG_EARLY_ADDRESS(x17, EXT(sheng_bootstrap_fb_trace_ready))
	ldr x16, [x17]
	cbz x16, 10f
	// 蓝色表示映射已准备，不能作为该阶段已执行的证据
	SHENG_BOOTSTRAP_TRACE 13, 0xff0080ff, 0
	SHENG_BOOTSTRAP_TRACE 14, 0xff0080ff, 0
	SHENG_BOOTSTRAP_TRACE 15, 0xff0080ff, 0
10:
#endif
.endmacro
