# 原生内核早期异常

sheng 的三段加载器交接已实机完成，尚无 XNU 控制台文字。
原 LowExceptionVectorBase 只会循环停机，较晚的 locore 日志不能覆盖这里。

0023 在 SHENG 冷启动入口建立低位向量后，使用 boot_args 的已验证 framebuffer 显示寄存器。
首行 `XNU=1` 证明内核汇编入口已执行；`XNU=2` 表示低位异常向量捕获异常并停机。
随后各行分别是 ELR、ESR、FAR、SPSR、SCTLR、TCR、TTBR0、TTBR1、MAIR。
入口状态下的 ELR/ESR/FAR 只是寄存器原值，只有状态 2 才作为本次异常解释。

处理器不依赖栈或 C 初始化。首次异常记录后再次异常会停机，保留第一份记录。
记录还保存 SP、MPIDR、boot_args、LR 和启动映射的 x22-x25。
代码、字形和记录都在原 4 KiB 向量页内，由汇编 .org 限制大小，复制后保持 PC 相对寻址。
OSLAR 访问移到建立向量之后，使该访问引起的异常也能保留。
该路径只负责 MMU 关闭时的早期现场；切换到正式异常向量后继续使用已有 locore 日志。
这不是 KDP 传输，也不证明跨重启 RAM 保留。

独立执行测试使用与内核相同的汇编头文件，验证入口正常返回、复制后的向量捕获真实 BRK、匹配 ELR/ESR，以及实际 framebuffer 输出。

```sh
python3 scripts/test_native_early_exception.py \
  --clang /home/rinnrei/Project/uwuAOSP/prebuilts/clang/host/linux-x86/clang-r596125/bin/clang \
  --qemu out/qemu-root/usr/bin/qemu-system-aarch64
```

独立 QEMU 测试已通过；完整 XNU 目标编译、真实内核启动与 sheng 实机结果分别记录。
