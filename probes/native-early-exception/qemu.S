// SPDX-License-Identifier: MIT
#ifdef __APPLE__
#define LowExceptionVectorBase _LowExceptionVectorBase
#endif
#define EXT(x) x
#define LEXT(x) x:
#define BA_VIDEO_BASE 40
#define BA_VIDEO_ROW_BYTES 56
#define BA_VIDEO_WIDTH 64
#define BA_VIDEO_HEIGHT 72
#define BA_VIDEO_DEPTH 80
.text
.global _start
_start:
 msr daifset, #15
 ldr x20, =boot_args
 mov x21, #0
 adr x0, LowExceptionVectorBase
 msr vbar_el1, x0
 isb
 bl Lsheng_early_enter
.global after_entry
after_entry:
 brk #0x123
 b .
.balign 4096
.global LowExceptionVectorBase
LowExceptionVectorBase:
.rept 16
 b Lsheng_early_exception
 .balign 128
.endr
#include "../../platform/sheng/macos26/log/early_exception.h"
.org LowExceptionVectorBase+4096
.data
.balign 8
boot_args:
 .space 40
 .quad 0x41000000,0,2560,640,640,32
