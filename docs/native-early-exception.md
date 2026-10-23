# 原生内核早期异常

sheng 的三段加载器交接已实机完成，尚无 XNU 控制台文字。
原 LowExceptionVectorBase 只会循环停机，较晚的 locore 日志不能覆盖这里。

0023 在 SHENG 冷启动入口建立低位向量后，使用 boot_args 的已验证 framebuffer 显示寄存器。
首行 `XNU=1` 证明内核汇编入口已执行；`XNU=2` 表示低位异常向量捕获异常并停机。
`XNU=3` 表示控制台建立前，正式 EL1 同步异常向量捕获了 MMU 开启时的异常。
随后各行分别是 ELR、ESR、FAR、SPSR、SCTLR、TCR、TTBR0、TTBR1、MAIR。
入口状态下的 ELR/ESR/FAR 只是寄存器原值，只有状态 2/3 才作为本次异常解释。

处理器不依赖栈或 C 初始化。首次异常记录后再次异常会停机，保留第一份记录。
记录还保存 SP、MPIDR、boot_args、LR 和启动映射的 x22-x25。
代码、字形和记录都在原 4 KiB 向量页内，由汇编 .org 限制大小，复制后保持 PC 相对寻址。
OSLAR 访问移到建立向量之后，使该访问引起的异常也能保留。
0024 在控制台建立前接入正式同步异常向量，保留故障时的控制寄存器。
SHENG未启用KTRR，配套 arm_vm_init.c 不裁剪原 bootstrap_pagetables 的 V=P 映射。
诊断路径只替换 TTBR0，保留当前 TTBR1，通过原始启动表切到物理取指地址，再关闭 MMU 显示故障现场。
ELR/ESR/FAR/SPSR/SCTLR/TCR/TTBR0/TTBR1/MAIR 保存的是切换前的故障状态。
这是控制台建立前的终止式诊断；该阶段遇到首个同步异常时停机，不能作为可恢复异常的处理实现。
PE_create_console完成后关闭该开关，恢复原有分发，locore保留日志继续工作。
背景按完整矩形覆盖，清除原 UEFI 文字，保留顶部交接色条。
这不是 KDP 传输，也不证明跨重启 RAM 保留。

独立执行测试使用与内核相同的汇编头文件，验证入口返回、复制后的向量捕获 BRK、16K高位执行且TTBR0关闭时的同步异常，以及关闭诊断开关后的正常分发。
MMU开启测试实际捕获ELR=0xffff8000402000e0、ESR=0xf2000124，显示原TTBR0=0与EPD0=1，没有用调试器直接填写故障记录。

```sh
python3 scripts/test_native_early_exception.py \
  --clang /home/rinnrei/Project/uwuAOSP/prebuilts/clang/host/linux-x86/clang-r596125/bin/clang \
  --qemu out/qemu-root/usr/bin/qemu-system-aarch64
```

独立 QEMU 测试已通过；完整 XNU 目标编译、真实内核启动与 sheng 实机结果分别记录。
