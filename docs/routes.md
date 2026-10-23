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
