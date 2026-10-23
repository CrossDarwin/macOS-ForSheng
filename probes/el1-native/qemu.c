// SPDX-License-Identifier: MIT
// 执行真实EL1探针，保留4K负对照，不能替代sheng实机结果
typedef unsigned long u64;
extern u64 ShengEl1GranuleProbe(u64 *, u64 *, u64, u64, u64);
extern u64 ShengEl1PauthProbe(u64 *);
static u64 original[2048] __attribute__((aligned(16384)));
static u64 trial[2048] __attribute__((aligned(16384)));
static u64 results[8], signatures[10];
static unsigned progress[12][512];

static u64 rd_sctlr(void)
{ u64 v; __asm__ volatile("mrs %0,sctlr_el1" : "=r"(v)); return v; }

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
    u64 el; __asm__ volatile("mrs %0,CurrentEL" : "=r"(el));
    if(el!=4) {print("FAIL EL1 entry\n");finish(1);}
    for(u64 i=0;i<2048;i++) {
        u64 leaf=i<2 ? 0 : (i<<(i<64 ? 30 : 25))|0x701;
        original[i]=trial[i]=leaf;
    }
    const u64 tcr=28UL|(1UL<<8)|(1UL<<10)|(3UL<<12)|(1UL<<23)|(5UL<<32);
    u64 control=(rd_sctlr()|1)&~(1UL<<19);
    __asm__ volatile("msr daifset,#15; msr mair_el1,%0; msr ttbr0_el1,%1; msr tcr_el1,%2;"
                     "dsb sy; tlbi vmalle1; dsb sy; isb; msr sctlr_el1,%3; isb"
                     ::"r"(0xffUL),"r"(original),"r"(tcr),"r"(control):"memory");
    u64 status=ShengEl1GranuleProbe(trial,results,tcr,(u64)progress,sizeof(progress[0]));
    for(unsigned stage=0;stage<16;stage++) {
        unsigned expected=0xff00;
#ifdef SHENG_GRANULE_INJECT_FAULT
        if(stage>=8 && stage<=11) expected=0;
#endif
        for(unsigned row=0;row<12;row++) {
            for(unsigned column=0;column<32;column++) {
                if(progress[row][stage*32+column]!=(column<24 ? expected : 0)) {
                    print("FAIL framebuffer checkpoint\n");finish(9);
                }
            }
        }
    }
#ifdef SHENG_GRANULE_INJECT_FAULT
    if(status!=1 || results[7]!=4 || (results[4]>>26)!=0) {
        print("FAIL EL1 exception recovery\n");finish(7);
    }
    print("PASS EL1 exception recorded and recovered\n");
#else
    if(status) {print("FAIL unexpected EL1 exception\n");finish(8);}
    if((results[0]&1) || (results[0]&0xfffffffff000UL)!=0x1000 ||
       !(results[1]&1) || !(results[2]&1)) {
        print("FAIL page-walk controls\n"); finish(2);
    }
#ifdef SHENG_GRANULE_FORCE_4K
    if(!(results[3]&1)) {print("FAIL 4K fallback accepted as 16K\n");finish(3);}
    print("PASS 4K fallback rejected\n");
#else
    if((results[3]&1) || (results[3]&0xfffffffff000UL)!=0x4001000) {
        print("FAIL 16K discriminator\n");finish(4);
    }
    print("PASS native 16K walk\n");
#endif
#endif
    u64 back_tcr,back_root,back_mair;
    __asm__ volatile("mrs %0,tcr_el1; mrs %1,ttbr0_el1; mrs %2,mair_el1"
                     :"=r"(back_tcr),"=r"(back_root),"=r"(back_mair));
    if(back_tcr!=tcr || back_root!=(u64)original || back_mair!=0xff || rd_sctlr()!=control) {
        print("FAIL MMU state restore\n");finish(5);
    }
    if(ShengEl1PauthProbe(signatures)!=0x7fff) {
        print("FAIL PAC bank switch or restore\n");finish(6);
    }
    print("PASS PAC IA IB DA DB GA switch and restore\n");
    finish(0);
}
