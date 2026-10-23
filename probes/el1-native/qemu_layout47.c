// SPDX-License-Identifier: MIT
#include "layout47.h"
typedef sheng47_u64 u64;
static u64 original[2048] __attribute__((aligned(16384)));
static u64 pages[SHENG47_BYTES / 8] __attribute__((aligned(16384)));
static u64 result[14];
static unsigned progress[12][512];

static void print(const char *s)
{
    register u64 op __asm__("x0")=4;
    register const char *arg __asm__("x1")=s;
    __asm__ volatile("hlt #0xf000" : "+r"(op) : "r"(arg) : "memory");
}

__attribute__((noreturn)) static void finish(u64 code)
{
    u64 args[2]={0x20026,code};
    register u64 op __asm__("x0")=0x20;
    register u64 *arg __asm__("x1")=args;
    __asm__ volatile("hlt #0xf000" : "+r"(op) : "r"(arg) : "memory");
    for(;;) __asm__ volatile("wfe");
}

void qemu_main(void);
void qemu_main(void)
{
    for(u64 i=0;i<2048;i++) {
        original[i]=i<2 ? 0 : (i<<(i<64 ? 30 : 25))|0x70d;
    }
    sheng47_tables(pages,3);
    unsigned char *code=(unsigned char *)pages+6*16384;
    const unsigned char *start=(const unsigned char *)ShengEl1Layout47Code;
    unsigned size=(unsigned)((u64)ShengEl1Layout47CodeEnd-(u64)start);
    for(unsigned i=0;i<size;i++) code[i]=start[i];
#ifdef SHENG_LAYOUT47_DENY_EXEC
    pages[2*2048+((SHENG47_LOW>>14)&2047)]|=1ULL<<53;
#endif
    const u64 tcr=28UL|(1UL<<8)|(1UL<<10)|(3UL<<12)|(1UL<<23)|(2UL<<30)|(5UL<<32);
    u64 control;
    __asm__ volatile("mrs %0,sctlr_el1":"=r"(control));
    control=(control|1|4|(1UL<<12))&~(1UL<<19);
    __asm__ volatile("msr daifset,#15; msr mair_el1,%0; msr ttbr0_el1,%1; msr ttbr1_el1,%1;"
                     "msr tcr_el1,%2; dsb sy; tlbi vmalle1; dsb sy; isb; msr sctlr_el1,%3; isb"
                     ::"r"(0xffbb4400UL),"r"(original),"r"(tcr),"r"(control):"memory");
    u64 status=ShengEl1Layout47Probe(pages,result,sheng47_tcr(tcr),(u64)progress,sizeof(progress[0]));
#if defined(SHENG_LAYOUT47_INJECT_FAULT) || defined(SHENG_LAYOUT47_DENY_EXEC)
    unsigned expected_ec=0;
#ifdef SHENG_LAYOUT47_DENY_EXEC
    expected_ec=0x21;
#endif
    if(status!=1 || result[13]!=2 || (result[10]>>26)!=expected_ec) {
        print("FAIL layout47 fault recovery\n");finish(1);
    }
#else
    if(status || (result[0]&1) || (result[1]&1) || (result[2]&1) ||
       (result[0]&0xfffffffff000UL)!=(u64)code ||
       (result[1]&0xfffffffff000UL)!=(u64)code ||
       (result[2]&0xfffffffff000UL)!=(u64)pages+7*16384 ||
       !(result[3]&1) || !(result[9]&1) ||
       result[4]!=SHENG47_LOW || result[5]!=SHENG47_CODE ||
       result[6]!=0x4747 || result[7]!=0x5757 || result[8]!=0x5757) {
        print("FAIL layout47 execution or controls\n");finish(2);
    }
#endif
    u64 back_tcr,back_root,back_upper,back_mair,back_sctlr;
    __asm__ volatile("mrs %0,tcr_el1; mrs %1,ttbr0_el1; mrs %2,ttbr1_el1; mrs %3,mair_el1; mrs %4,sctlr_el1"
                     :"=r"(back_tcr),"=r"(back_root),"=r"(back_upper),"=r"(back_mair),"=r"(back_sctlr));
    if(back_tcr!=tcr || back_root!=(u64)original || back_upper!=(u64)original ||
       back_mair!=0xffbb4400 || back_sctlr!=control) {
        print("FAIL layout47 firmware restore\n");finish(3);
    }
    for(unsigned stage=0;stage<16;stage++) {
        unsigned expected=0xff00;
#if defined(SHENG_LAYOUT47_INJECT_FAULT) || defined(SHENG_LAYOUT47_DENY_EXEC)
        if(stage>=8 && stage<=11) expected=0;
#endif
        for(unsigned row=0;row<12;row++) {
            for(unsigned col=0;col<32;col++) {
                if(progress[row][stage*32+col]!=(col<24 ? expected : 0)) {
                    print("FAIL layout47 checkpoints\n");finish(4);
                }
            }
        }
    }
    print("PASS layout47 execution controls and firmware restore\n");
    finish(0);
}
