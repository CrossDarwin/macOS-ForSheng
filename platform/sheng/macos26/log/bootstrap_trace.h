/* SPDX-License-Identifier: MIT */
/* 仅冷启动且MMU关闭时使用，x16-x18和NZCV为临时状态 */
.macro SHENG_BOOTSTRAP_TRACE stage
#if SHENG
	cbnz x21, 9f
	mov x16, #\stage
	adr x17, EXT(sheng_early_exception_record)
	str x16, [x17, #184]
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
	mov x18, #0xff00
	movk x18, #0xff00, lsl #16
	movk x18, #0xff00, lsl #32
	movk x18, #0xff00, lsl #48
	.rept 12
	stp x18, x18, [x16]
	str w18, [x16, #16]
	add x16, x16, x17
	.endr
	dsb sy
9:
#endif
.endmacro
