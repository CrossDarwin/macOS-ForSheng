# macOS 26 配对与启动路线

当前系统基线为 macOS 26.5 / 25F71。内核、恢复卷与系统用户空间都取自同一 IPSW。
不把 macOS 26 内核与 macOS 27 用户空间拼接，也不把 Darwin 23 的硬件实验当作系统启动。

Apple 的 [macOS 26.5 源码清单](https://github.com/apple-oss-distributions/distribution-macOS/tree/macos-265)
固定 XNU 12377.121.6。2026-10-23 检查官方发布与标签，尚未取得 macOS 27 / XNU 13432 对应公开源码。
这是当前源码发布范围，不是 XNU 能支持的系统版本上限。
版本号相近不能证明内核、私有驱动、dyld 与 launchd 的 ABI 兼容。配对输入也不能替代硬件适配。

同一个 25F71 IPSW 包含下列身份。BuildManifest 中三者的 BaseSystem、OS 与 SystemOS 路径一致，内核不同。

| 候选 | 身份与内核 | 源码依据 | 当前判断 |
| --- | --- | --- | --- |
| M1 | j313ap / mac13g / T8103 | T8103 不在 `SPTM_ENABLED_SOCS_MacOSX` 列表中 | 优先研究原生 EL1 适配；仍需处理 Apple CPU、页表、异常及驱动依赖 |
| MacBook Neo | j700ap / mac17p / T8140 | 清单含 TXM，较新的 Apple CPU 与安全启动要求 | 保留对照，不能直接套用 Snapintosh 27 的固定地址和哈希 |
| 虚拟 Mac | vma2macosap / vma2 / VMAPPLE | `NO_MONITOR`、GICv3；仍有 HVC PAC 密钥请求及其他虚拟设备契约 | 当前没有自主管理的 EL2，不能直接运行原版 VM 内核 |

以上优先级来自依赖数量与已知 EL1 入口，尚无实机 macOS 成功率数据。
M1 缺少 SPTM 配置不代表原版内核可直接运行于 sheng。

源码锚点来自固定提交 `ac9718fb1af618d5ce8678d0dc6e8a58f252216f`：

- [MakeInc.def](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/makedefs/MakeInc.def)：Mac SoC 与 SPTM 启用集合
- [VMAPPLE.h](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/pexpert/pexpert/arm64/VMAPPLE.h)：虚拟平台特性契约
- [machine_routines_apple.c](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/arm/machine_routines_apple.c)：VMAPPLE PAC 密钥 HVC 路径

先以 UniXNU 的 XNU 10063.141.1 验证退出 UEFI、异常入口、定时器和初始页表。
完整基线包含全部上游驱动，但测试参数未启用 UFS 控制器；不含 macOS 用户空间。
实机已通过控制台、IOKit、BSD 初始化，并在根设备查找前按设计复位。
随后将确有运行证据的平台实现移到 12377.121.6，处理该版本的 CPU、引导参数和驱动 ABI。
恢复卷、launchd、WindowServer 的验收从配对的 25F71 开始。

Snapintosh 的 SPTM/TXM 与客体兼容代码继续作为参考；当前 EL1 入口无法运行其现有 EL2 监控层。
发现原生路线不能满足的具体依赖时，记录函数、异常与寄存器，再判断需要内核改动还是新的固件入口。

## Snapintosh 实现对照（2026-10-23）

已另行浅克隆组织仓库，固定在 `config/snapintosh-reference-sources.json`，不更新原有构建依赖。
Snapintosh 提交为 `2c60b47a950f6d98caed6b2551adc227f8ced4c9`，q1n1 为 `b72baceeafbdc28c866838e000146455a9f4a653`。

上游使用配套 26A428 的原版 J700 kernelcache、设备树、SPTM/TXM 输入，不重新编译 XNU。
EL2 监控层实现 SPTM/TXM 调用，维护 16 KiB 客体表和 4 KiB 实际影子表；NV2 将客体的 EL2 寄存器访问重定向到 VNCR。
硬件驱动通过 KDK 和 kmutil 链接到 AuxKC。少量可选内核补丁用于已测得的陷入成本，不提供 sheng 的 EL1 实现。
依据：[启动链](https://github.com/Snapintosh/Snapintosh/blob/2c60b47a950f6d98caed6b2551adc227f8ced4c9/docs/BOOT-CHAIN.md)、
[构建说明](https://github.com/Snapintosh/Snapintosh/blob/2c60b47a950f6d98caed6b2551adc227f8ced4c9/docs/BUILDING.md)。

| 条件 | 上游实际实现 | sheng 的依据与处理 |
| --- | --- | --- |
| EL2 入口 | q1n1 的 A16 实机记录为固件直接进入 EL2；`HostRuntime.from_q1n1` 拒绝 EL1 | 已有 UEFI 探针 CPU0 为 EL1；更换 q1n1 不会自行获得 EL2 |
| NV2 | `probes/xnuboot/prepare.c` 设置 HCR.NV/NV2 和 VNCR | CPU0 MMFR2=`0x1221011110101011`，NV=0；不是其已支持的主机 |
| 16 KiB | A16 的区分性 `AT S1E1R` 实测失败，所以使用影子表 | sheng MMFR0 的 TGran16=1 仅是能力声明；需要真正页表执行，不能直接运行上游需要 EL2 的探针 |
| arm64e/PAC | `compat/pauth-domain.c` 派生兼容密钥域，`pauth-switch.S` 在用户返回前安装密钥、异常进入后恢复；汇编检查 CurrentEL=2 | Android PACIA/AUTIA 往返只证明指令可用；必须适配 EL1 的密钥保存/恢复、进程切换和用户返回 |
| 存储 | `compat/ans.c` 将 Apple ANS 接到实际 NVMe 后端 | sheng 使用 UFS；复用 UniXNU 的硬件实现，不能沿用 A16 的 NVMe 寄存器 |

q1n1 的可选 slbounce 是 Qualcomm PC Secure Launch/QHEE 路径，依赖签名 tcblaunch 和对应固件协议。
A16 已记录的成功启动没有使用它。当前没有 sheng 的 Gunyah 支持该协议的证据，不能将它当作通用 EL1→EL2 跳板。
依据：[A16 EL2 实机记录](https://github.com/Snapintosh/q1n1/blob/b72baceeafbdc28c866838e000146455a9f4a653/docs/A16-FIRST-EL2-BOOT.md)、
[slbounce 原理](https://github.com/TravMurav/slbounce/blob/c090a8cdafa25e4c99df90f8d6f73f3805d9b397/theory_of_operation.md)。

当前路线保留配套 macOS 26 的原生 EL1 实验，但尚未形成可启动用户空间的方案。
后续实现先处理两个实际条件：sheng 的 16 KiB/47 位页表执行，以及 arm64e 用户空间的密钥生命周期。
后者需要同时处理 `do_cpuid`、`ml_grade_binary`、PAC 密钥初始化、上下文切换与异常返回。
目前未定义 HAS_APPLE_PAC 的 SHENG 会报告 ARMv8，并拒绝 arm64e 二进制；不能只修改 subtype 放行或直接定义 Apple PAC。
参考 Snapintosh 的密钥域和切换语义，采用适合 EL1 的实现；其需要 HCR_EL2 的汇编不直接搬入。
只有这些条件成立，才继续恢复卷、launchd 和新版驱动集合；不以旧内核继续增加检查点或把归档成功当作系统启动。

## 社区与高通固件入口补充（2026-10-23）

重新检索时发现高通自己的开源固件已有另一条 EL2 入口，不能把上述 slbounce 边界扩大成所有高通设备均无法退出 Gunyah。
EDK2 `KodiakHelper.S` 在早期 PEI 阶段调用 TrustZone：服务 ID `0x02000121`、参数 ID `0x23`，退出参数为 1。
其说明包括退出 Gunyah并清理 SMMU 配置；它改变当前执行环境，不能在普通 UEFI 应用中照抄后返回。
高通 U-Boot 的对应实现也放在 `start.S` 配置 EL 寄存器之前，PR #64 修正了本来已处于 EL2 时的分支。

这证明部分高通固件提供该机制，不证明 sheng 的量产 TrustZone 实现支持它。
目前未在 sheng 调用该服务，也未获得其可用性查询结果。
后续先按 Qualcomm SCM 的 INFO/IS_CALL_AVAIL 契约区分“服务存在”与“实际允许退出”，再决定是否制作独立早期入口。
即使取得 EL2，CPU0 已测 NV=0 仍与 Snapintosh 当前 NV2 后端不匹配；两项条件分别处理。

来源：[EDK2 早期入口](https://github.com/tianocore/edk2-platforms/blob/master/Silicon/Qualcomm/KodiakPkg/Library/KodiakLib/KodiakHelper.S)、
[服务参数](https://github.com/tianocore/edk2-platforms/blob/master/Silicon/Qualcomm/KodiakPkg/Library/KodiakLib/KodiakHelper.h)、
[U-Boot 原始讨论](https://lists.u-boot-project.org/pipermail/u-boot/2026-May/618654.html)、
[高通修正 PR](https://github.com/qualcomm-linux/u-boot/pull/64)、
[SCM 可用性查询](https://github.com/torvalds/linux/blob/v6.12/drivers/firmware/qcom/qcom_scm.c#L318)。

当前原生探针改为闲置 TTBR1 高地址窗口的真实页表遍历，保留 UEFI 的 TTBR0/TG0、MAIR 和 SCTLR。
这是解决 MMU 关闭阶段显示干扰的实验设计，不是已经证明 sheng 可执行 16K 内核代码。
