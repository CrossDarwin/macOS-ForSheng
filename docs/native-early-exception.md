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

0027增加MMU关闭阶段的`STAGES 0123456789ABCDEF`条。绿色格子表示该标记的显存写入已完成，灰色表示未标记。
所有标记都在首次开启MMU之前，不把C格变绿记作MMU已成功开启。
不依赖栈、函数调用、固件、串口或高位framebuffer映射；仅使用当前启动路径不再持有的x16-x18和NZCV。
首次异常记录的偏移184保留最后阶段，复制后的4 KiB向量页仍完整包含现场。

| 格子 | 已执行到的位置 |
| --- | --- |
| 0 | 入口寄存器页返回 |
| 1 | 读取启动参数 |
| 2 | 线程寄存器、启动栈和C入口地址准备完成 |
| 3 | 启动页表池清零完成 |
| 4 | V=P映射建立完成 |
| 5 | 高位KVA映射建立完成 |
| 6 | 即将写TCR |
| 7 | TCR写入返回 |
| 8 | TTBR0写入返回 |
| 9 | TTBR1写入返回 |
| A | MAIR写入返回 |
| B | 初始TLBI和I-cache维护指令返回 |
| C | 即将写SCTLR开启MMU |
| D | SCTLR开启MMU后的ISB返回 |
| E | 高位正式VBAR写入及ISB完成 |
| F | 高位交接代码已执行，即将返回arm_init |

标记本身增加显存写入和DSB，可能改变时序；若只出现半格，不将它当作完整阶段通过。
0028在MMU开启前为阶段条建立临时TTBR0 identity映射。
范围限定为阶段条所在的至多两个32 MiB块，使用Device-nGnRnE和PXN/UXN，不覆盖已有映射。
已有L2必须在原生bootstrap页表池内；缺少L2时使用独立16 KiB页，不侵占内核映射。
映射就绪时D–F先显示蓝色，执行到各阶段才变绿；灰色表示诊断映射未准备，不能据此认定MMU卡死。
标记不依赖栈，不切回MMU关闭状态，不修改EL2或固件。
F只能证明高位交接代码执行，尚不证明arm_init中的PAC、重定位或C初始化完成。
arm_vm_init按原流程替换TTBR1并停用TTBR0，后续控制台使用其原有映射。
PE_create_console完成后关闭该开关，恢复原有分发，locore保留日志继续工作。
0025修正首次开启MMU时的向量交接：先保留V=P向量，SCTLR写入和ISB完成后才安装高位正式向量。
低位入口遇到MMU已开启时，直接进入无栈的物理恢复路径，不先写入可能只读的向量页。
这样能够覆盖高位页表失效、异常栈不可用而V=P映射仍有效的首次取指异常。
若V=P映射本身也失效、异常被更高异常级截获或代码无异常地循环，屏幕路径仍无法保证输出。
背景按完整矩形覆盖，清除原 UEFI 文字，保留顶部交接色条。
这不是 KDP 传输，也不证明跨重启 RAM 保留。

独立执行测试使用与内核相同的汇编头文件，验证入口返回、复制后的向量捕获 BRK、16K高位执行且TTBR0关闭时的同步异常，以及关闭诊断开关后的正常分发。
MMU开启测试实际捕获ELR=0xffff8000402000e0、ESR=0xf2000124，显示原TTBR0=0与EPD0=1，没有用调试器直接填写故障记录。
新增首次翻译故障测试：实际清空TTBR1并将SP置零，向高位地址取指触发异常。
捕获XNU=3、ELR/FAR=0xffff800040000000、ESR=0x86000005，原TTBR1和SP均为0。

```sh
python3 scripts/test_native_early_exception.py \
  --clang /home/rinnrei/Project/uwuAOSP/prebuilts/clang/host/linux-x86/clang-r596125/bin/clang \
  --qemu out/qemu-root/usr/bin/qemu-system-aarch64
```

独立 QEMU 测试已通过；完整 XNU 目标编译、真实内核启动与 sheng 实机结果分别记录。

`scripts/observe_native_bootstrap.py`补充实际链接内核的高物理地址观察。
使用sheng照片中的kernel PA `0x881004000`与boot_args PA `0x882A00000`，执行原始启动汇编。
通过GDB在`arm_init`第一条指令前停止，同时核对实际指令、启动参数和控制寄存器。
该观察不经过UEFI，不提供设备树或framebuffer，不执行C初始化，也不模拟Gunyah或sheng设备。
QEMU配置34 GiB稀疏客体RAM，仅为覆盖该物理地址；XNU收到的owned window仍是512 MiB。
`--framebuffer-trace`提供sheng的0xB8000000、3048×2032、stride12192几何，实际读取16个标记像素并要求全绿。
它用于验证新映射及显存写入，仍不模拟真实显示控制器或Gunyah。

```sh
python3 scripts/observe_native_bootstrap.py \
  --kernel-build private/ci/macos26-arm64e-kernel-39987628332 \
  --clang /home/rinnrei/Project/uwuAOSP/prebuilts/clang/host/linux-x86/clang-r596125/bin/clang \
  --qemu out/qemu-root/usr/bin/qemu-system-aarch64 \
  --output out/native-bootstrap-high-pa-39987628332
```
