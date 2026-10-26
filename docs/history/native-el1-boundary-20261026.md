# 调查记录 - native-el1-boundary

本页保留 2026-10-26 及此前的实现调查，不作为当前操作指南。
阶段性“尚未通过”和“下一步”仅适用于对应记录，现状见[移植状态](../status.md)。

# sheng的EL1适配边界

当前实机入口是EL1。没有取得Gunyah所在的EL2控制权，也没有证据确认当前停顿由Gunyah造成。

Snapintosh的基线不同：q1n1从UEFI取得EL2，监控层设置HCR、MDCR、VNCR、VTTBR和VTCR。
它用NV2承接原版XNU的EL2寄存器访问，以stage-2和shadow页表实现所需地址空间，并模拟SPTM/TXM。
这些控制不能靠在EL1执行同一条MSR完成。

参考固定源码：

- `sources/reference/Snapintosh/docs/BOOT-CHAIN.md`
- `sources/reference/Snapintosh/probes/xnuboot/prepare.c`中的`vcpu_arch_prepare`
- `sources/reference/Snapintosh/docs/KERNEL-PATCHES.md`中的System-register zeroing

| 项目 | 当前处理 |
| --- | --- |
| Apple专用CPU tunables、SPTM/PPL/监控层使能 | 使用已有UniXNU参考和原生SHENG配置避开 |
| Apple PMU计数器 | SHENG不选择该配置，不用伪造读数维持原Apple路径 |
| 启动阶段OSLAR硬件调试解锁 | 0026在SHENG冷启动和reset入口跳过；不影响软件日志和BRK异常机制 |
| 地址翻译、PAC、GIC、定时器 | 必须实现并保留，不能通过NOP假装初始化成功 |
| EL2陷入开关、第二阶段页表、NV2 | 当前EL1不能直接修改，需要EL2控制权或明确开放的固件接口 |
| Gunyah退出 | 当前没有已确认可用的退出接口，不把禁用XNU组件记作关闭Gunyah |

Snapintosh只对已经确认返回0、忽略写入的18种寄存器做等价改写，不是屏蔽所有特权访问。
当前使用自构建的EL1内核，优先在源码中排除无用功能，不把原版内核的寄存器列表直接套入。

## 已验证的调试寄存器陷入对照

原A7ED53F3内核在普通QEMU中可从实机物理地址0x881004000执行到arm_init。
同一内核放在QEMU的EL1，测试宿主仅开启MDCR_EL2.TDOSA，运行时实际陷入EL2：

```
MDCR_EL2 = 0x400
ELR_EL2  = 0x8815BA07C
ESR_EL2  = 0x622807E0
word     = 0xD510109F  // MSR OSLAR_EL1, XZR
ESR_EL1  = 0
```

该指令正是XNU=1绘制返回后的下一条指令。
这证明外层调试陷入能够形成“入口状态1、EL1没有异常”的现象，不证明实机Gunyah设置了该位。
0026只移除不依赖的早期硬件调试解锁，不修改HYP/TZ/XBL/ABL，不关闭Gunyah。
硬件断点和观察点没有因此取得可用性；KDP仍需实际传输后端。

Arm对[MDCR_EL2及OS调试寄存器的说明](https://documentation-service.arm.com/static/5e7b6c837158f500bd5c03fc)给出该陷入机制。
QEMU的[MDCR_TDOSA定义](https://github.com/qemu/qemu/blob/master/target/arm/internals.h)为bit10。

```sh
python3 scripts/observe_native_bootstrap.py \
  --kernel-build private/ci/macos26-arm64e-kernel-39990930289 \
  --clang /path/to/llvm/bin/clang \
  --qemu out/qemu-root/usr/bin/qemu-system-aarch64 \
  --output out/native-bootstrap-debug-trap-control-39990930289 \
  --trap-debug-unlock --expect-debug-trap
```

新版构建的对照使用`--trap-debug-unlock`而不加`--expect-debug-trap`，必须在同一陷入策略下到达真实arm_init入口。

Actions 39992979541构建的新内核UUID为C9819D72-7190-3DF2-877C-6F93C6F722F5。
同一物理地址及MDCR_EL2=0x400策略下，实际到达arm_init=0xfffffe0007c87b08，入口指令及x0启动参数匹配。
ESR_EL2=0，SCTLR=0xFC54793D；这是QEMU中对0026的实际对照结果，尚待sheng实机反馈。

GBL本身不构成新的EL2入口。[AOSP部署文档](https://source.android.com/docs/core/architecture/bootloader/generic-bootloader/gbl-dev)将其定义为UEFI应用；[Arm EBBR规范](https://github.com/ARM-software/ebbr/blob/main/source/chapter2-uefi.rst#aarch64-exception-levels)说明UEFI应用可能在EL1或EL2执行，取决于上游固件环境。
sheng当前链路已经实测为EL1，尚无证据表明更早GBL入口可取得EL2。若后续找到这种入口，仍需确认其交接状态及对真实EL2的控制；仅有GBL、解锁或任意UEFI代码执行不改变当前EL1路线。
