# sheng 的 EL1 适配边界

当前 ABL/UEFI 链路将启动核交接到 EL1。SHENG 在此级别执行原生内核，不控制 Gunyah 所在的真实 EL2。
本页说明该交接级别下的平台职责、受限寄存器及已有陷入对照。

## 可用机制与缺失控制

| 项目 | 当前处理 |
| --- | --- |
| 地址翻译、PAC、GIC、定时器 | 由 SHENG EL1 平台实现，保留真实初始化与错误处理 |
| Apple 专用 CPU tunables、SPTM/PPL | 使用 SHENG 原生配置，排除不适用路径 |
| 早期 OSLAR 调试解锁 | 冷启动和 reset 路径跳过不依赖的硬件调试解锁 |
| HCR、MDCR、VTTBR、VTCR、VNCR、第二阶段页表 | 当前 EL1 不能直接控制，需要真实 EL2 或明确的固件服务 |
| Gunyah 退出 | 没有已确认适用于 sheng 的退出接口 |
| KDP | 内核保留实现，实机双向轮询后端尚未接通 |

SHENG 配置排除不适用的 Apple 功能，并保留地址翻译、中断及定时器等实际平台实现。
这些源码改动不修改 HYP/TZ 或外层监控程序的状态。

## 调试陷入对照

QEMU 对照将 `MDCR_EL2.TDOSA` 置位后，原启动代码在 `MSR OSLAR_EL1, XZR` 实际陷入 EL2，
EL1 没有对应异常记录。移除该次早期解锁后，同一策略下内核到达 arm_init。
这证明外层调试陷入能形成旧 `XNU=1` 停顿现象，不证明实机设置了相同控制位。
该修正不授予硬件断点、观察点或调试传输能力。
地址、寄存器和旧候选记录见[历史对照](history/native-el1-boundary-20261026.md)。

GBL 是 UEFI 应用，执行级别由上游固件交接决定；应用本身不会把 EL1 提升为 EL2。
当前实现沿用原生 EL1 用户态路线，运行状态见[移植状态](status.md)。

参考：[AOSP GBL 部署说明](https://source.android.com/docs/core/architecture/bootloader/generic-bootloader/gbl-dev)、
[Arm EBBR 的 AArch64 执行级别](https://github.com/ARM-software/ebbr/blob/main/source/chapter2-uefi.rst#aarch64-exception-levels)、
[Snapintosh 固定启动链](https://github.com/Snapintosh/Snapintosh/blob/2c60b47a950f6d98caed6b2551adc227f8ced4c9/docs/BOOT-CHAIN.md)。
