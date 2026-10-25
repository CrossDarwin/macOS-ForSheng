/* SPDX-License-Identifier: MIT */
/* Copy with the low vectors; require no stack, C globals, firmware, or MMIO UART. */
#ifndef SHENG_EARLY_ADDRESS_DEFINED
#define SHENG_EARLY_ADDRESS_DEFINED
/* Darwin assembly treats semicolons as comments; place each instruction on its own line. */
.macro SHENG_EARLY_ADDRESS reg, name
#ifdef __APPLE__
    adrp \reg, \name@page
    add \reg, \reg, \name@pageoff
#else
    adrp \reg, \name
    add \reg, \reg, :lo12:\name
#endif
.endmacro
#endif
Lsheng_early_enter:
	adr x19, EXT(sheng_early_exception_record)
	str x20, [x19, #96]
	str lr, [x19, #104]
	str x20, [x19, #176]
	ldp x0, x1, [x20, BA_VIRT_BASE]
	stp x0, x1, [x19, #144]
	SHENG_EARLY_ADDRESS x0, EXT(bootstrap_pagetables)
	str x0, [x19, #160]
	adr x0, Lsheng_mmu_off_fault
	str x0, [x19, #168]
	mov x0, #-1
	str x0, [x19, #184]
	mov x0, #1
	str x0, [x19]
	b Lsheng_early_capture

Lsheng_early_exception:
	msr DAIFSet, #15
	/* Use V=P vectors for the first MMU transition without high mappings or an exception stack. */
	mrs x0, SCTLR_EL1
	tbnz x0, #0, EXT(sheng_mmu_sync_fault)
	adr x19, EXT(sheng_early_exception_record)
	ldr x0, [x19]
	cmp x0, #2
	b.hs Lsheng_early_halt
	mov x0, #2
	str x0, [x19]
	str x20, [x19, #96]
	str lr, [x19, #104]
Lsheng_early_capture:
	stp x22, x23, [x19, #112]
	stp x24, x25, [x19, #128]
	mrs x0, ELR_EL1
	str x0, [x19, #8]
	mrs x0, ESR_EL1
	str x0, [x19, #16]
	mrs x0, FAR_EL1
	str x0, [x19, #24]
	mrs x0, SPSR_EL1
	str x0, [x19, #32]
	mrs x0, SCTLR_EL1
	str x0, [x19, #40]
	mrs x0, TCR_EL1
	str x0, [x19, #48]
	mrs x0, TTBR0_EL1
	str x0, [x19, #56]
	mrs x0, TTBR1_EL1
	str x0, [x19, #64]
	mrs x0, MAIR_EL1
	str x0, [x19, #72]
	mov x0, sp
	str x0, [x19, #80]
	mrs x0, MPIDR_EL1
	str x0, [x19, #88]
	dsb sy

	/* Low vectors run only with the MMU off; never treat the physical framebuffer as a mapped VA. */
	ldr x0, [x19, #40]
	tbnz x0, #0, Lsheng_early_finish
Lsheng_early_draw:
	ldr x0, [x19, #96]
	cbz x0, Lsheng_early_finish
	ldr x21, [x0, BA_VIDEO_BASE]
	cbz x21, Lsheng_early_finish
	ldr x22, [x0, BA_VIDEO_ROW_BYTES]
	cmp x22, #2560
	b.lo Lsheng_early_finish
	mov x1, #65536
	cmp x22, x1
	b.hi Lsheng_early_finish
	ldr x1, [x0, BA_VIDEO_WIDTH]
	cmp x1, #640
	b.lo Lsheng_early_finish
	lsr x2, x22, #2
	cmp x1, x2
	b.hi Lsheng_early_finish
	ldr x1, [x0, BA_VIDEO_HEIGHT]
	cmp x1, #640
	b.lo Lsheng_early_finish
	mov x2, #16384
	cmp x1, x2
	b.hi Lsheng_early_finish
	ldr x1, [x0, BA_VIDEO_DEPTH]
	and x1, x1, #255
	cmp x1, #32
	b.ne Lsheng_early_finish
	/* Clear the full text background, including character and line spacing. */
	mov x0, #112
	madd x0, x0, x22, x21
	add x0, x0, #64
	mov x1, #496
	mov w5, #0xff000000
Lsheng_early_clear_row:
	mov x2, #152
	mov x3, x0
Lsheng_early_clear_pixels:
	stp w5, w5, [x3], #8
	stp w5, w5, [x3], #8
	subs x2, x2, #1
	b.ne Lsheng_early_clear_pixels
	add x0, x0, x22
	subs x1, x1, #1
	b.ne Lsheng_early_clear_row
	adr x23, Lsheng_early_font
	adr x24, Lsheng_early_labels
	mov x26, #0
Lsheng_early_row:
	/* Reserve the first ten rows for registers and the last row for stage labels. */
	mov x0, #40
	madd x0, x26, x0, xzr
	add x0, x0, #128
	madd x27, x0, x22, x21
	add x27, x27, #128
	ldr x18, [x19, x26, lsl #3]
	cmp x26, #10
	b.ne 1f
	mov x18, #0xcdef
	movk x18, #0x89ab, lsl #16
	movk x18, #0x4567, lsl #32
	movk x18, #0x0123, lsl #48
1:
	mov x28, #0
Lsheng_early_char:
	cmp x28, #8
	b.hs Lsheng_early_digit
	add x0, x28, x26, lsl #3
	ldrb w0, [x24, x0]
	cmp w0, #32
	b.eq Lsheng_early_space
	cmp w0, #65
	b.lo Lsheng_early_label_digit
	sub w0, w0, #55
	b Lsheng_early_glyph
Lsheng_early_label_digit:
	sub w0, w0, #48
	b Lsheng_early_glyph
Lsheng_early_space:
	mov w0, #36
	b Lsheng_early_glyph
Lsheng_early_digit:
	mov x0, #23
	sub x0, x0, x28
	lsl x0, x0, #2
	lsr x0, x18, x0
	and x0, x0, #15
Lsheng_early_glyph:
	lsl x1, x0, #3
	sub x1, x1, x0
	add x1, x23, x1
	mov x2, #0
Lsheng_early_glyph_row:
	ldrb w3, [x1, x2]
	lsl x4, x2, #2
	madd x4, x4, x22, x27
	mov x5, #4
Lsheng_early_pixel:
	lsr w6, w3, w5
	and w6, w6, #1
	neg w6, w6
	orr w6, w6, #0xff000000
	mov x7, #4
	mov x8, x4
Lsheng_early_pixel_rows:
	stp w6, w6, [x8]
	stp w6, w6, [x8, #8]
	add x8, x8, x22
	subs x7, x7, #1
	b.ne Lsheng_early_pixel_rows
	add x4, x4, #16
	subs x5, x5, #1
	b.pl Lsheng_early_pixel
	add x2, x2, #1
	cmp x2, #7
	b.lo Lsheng_early_glyph_row
	cmp x26, #10
	b.ne 2f
	cmp x28, #8
	b.lo 2f
	mov x0, #40
	madd x0, x0, x22, x27
	mov x1, #12
	mov w3, #0x3030
	movk w3, #0xff30, lsl #16
	ldr x2, [x19, #184]
	cmp x2, #16
	b.hs 3f
	sub x4, x28, #8
	cmp x4, x2
	b.hi 3f
	mov w3, #0xff00
	movk w3, #0xff00, lsl #16
3:
1:
	stp w3, w3, [x0]
	stp w3, w3, [x0, #8]
	str w3, [x0, #16]
	add x0, x0, x22
	subs x1, x1, #1
	b.ne 1b
2:
	add x27, x27, #96
	add x28, x28, #1
	cmp x28, #24
	b.lo Lsheng_early_char
	add x26, x26, #1
	cmp x26, #11
	b.lo Lsheng_early_row
	dsb sy
Lsheng_early_finish:
	ldr x0, [x19]
	cmp x0, #1
	b.ne Lsheng_early_halt
	ldr x20, [x19, #96]
	ldr lr, [x19, #104]
	mov x21, #0
	ret
Lsheng_early_halt:
	b Lsheng_early_halt

/* Use the normal vector entry only before console setup and preserve system registers from the fault. */
	.globl EXT(sheng_mmu_sync_fault)
LEXT(sheng_mmu_sync_fault)
	msr DAIFSet, #15
	mrs x9, ELR_EL1
	mrs x10, ESR_EL1
	mrs x11, FAR_EL1
	mrs x12, SPSR_EL1
	mrs x13, SCTLR_EL1
	mrs x14, TCR_EL1
	mrs x15, TTBR0_EL1
	mrs x16, TTBR1_EL1
	mrs x17, MAIR_EL1
	mrs x18, SP_EL0
	tbz x12, #0, 1f
	mov x18, sp
1:
	SHENG_EARLY_ADDRESS x0, EXT(sheng_early_exception_record)
	ldr x1, [x0, #160]
	ldr x2, [x0, #168]
	ldr x3, [x0, #176]
	/* SHENG does not use KTRR; bootstrap tables retain a V=P mapping for the kernel window. */
	msr TTBR0_EL1, x1
	isb
	mov x4, #0xc0bf
	bic x5, x14, x4
	mov x4, #0x8011
	orr x5, x5, x4
	msr TCR_EL1, x5
	isb
	tlbi vmalle1
	dsb ish
	isb
	br x2

Lsheng_mmu_off_fault:
	/* Instruction fetch is already V=P; do not use the old exception stack after disabling translation. */
	adr x0, EXT(LowExceptionVectorBase)
	msr VBAR_EL1, x0
	isb
	bic x0, x13, #1
	bic x0, x0, #4
	bic x0, x0, #0x1000
	msr SCTLR_EL1, x0
	isb
	tlbi vmalle1
	dsb sy
	isb
	adr x19, EXT(sheng_early_exception_record)
	mov x0, #3
	str x0, [x19]
	stp x9, x10, [x19, #8]
	stp x11, x12, [x19, #24]
	stp x13, x14, [x19, #40]
	stp x15, x16, [x19, #56]
	stp x17, x18, [x19, #72]
	mrs x0, MPIDR_EL1
	str x0, [x19, #88]
	str x3, [x19, #96]
	str lr, [x19, #104]
	stp x22, x23, [x19, #112]
	stp x24, x25, [x19, #128]
	dsb sy
	b Lsheng_early_draw

Lsheng_early_labels:
	.ascii "XNU     ELR     ESR     FAR     SPSR    SCTLR   TCR     TTBR0   TTBR1   MAIR    STAGES  "
Lsheng_early_font:
	/* Glyphs cover 0-9, A-Z, and space, with seven rows and five columns each. */
	.byte 14,17,19,21,25,17,14
	.byte 4,12,4,4,4,4,14
	.byte 14,17,1,2,4,8,31
	.byte 30,1,1,14,1,1,30
	.byte 2,6,10,18,31,2,2
	.byte 31,16,16,30,1,1,30
	.byte 14,16,16,30,17,17,14
	.byte 31,1,2,4,8,8,8
	.byte 14,17,17,14,17,17,14
	.byte 14,17,17,15,1,1,14
	.byte 14,17,17,31,17,17,17
	.byte 30,17,17,30,17,17,30
	.byte 14,17,16,16,16,17,14
	.byte 30,17,17,17,17,17,30
	.byte 31,16,16,30,16,16,31
	.byte 31,16,16,30,16,16,16
	.byte 14,17,16,23,17,17,15
	.byte 17,17,17,31,17,17,17
	.byte 14,4,4,4,4,4,14
	.byte 7,2,2,2,2,18,12
	.byte 17,18,20,24,20,18,17
	.byte 16,16,16,16,16,16,31
	.byte 17,27,21,21,17,17,17
	.byte 17,25,21,19,17,17,17
	.byte 14,17,17,17,17,17,14
	.byte 30,17,17,30,16,16,16
	.byte 14,17,17,17,21,18,13
	.byte 30,17,17,30,20,18,17
	.byte 15,16,16,14,1,1,30
	.byte 31,4,4,4,4,4,4
	.byte 17,17,17,17,17,17,14
	.byte 17,17,17,17,17,10,4
	.byte 17,17,17,21,21,21,10
	.byte 17,17,10,4,10,17,17
	.byte 17,17,10,4,4,4,4
	.byte 31,1,2,4,8,16,31
	.byte 0,0,0,0,0,0,0
	.p2align 3
	.globl EXT(sheng_early_exception_record)
LEXT(sheng_early_exception_record)
	.space 192, 0
