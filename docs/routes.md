# 原生 EL1 启动路线

sheng 当前通过 ABL 和 UEFI 临时启动自构建 SHENG 内核，交接级别为 EL1。
系统输入统一使用 macOS 26.5 / 25F71，不混用旧 iPadOS 内核或 macOS 27 用户空间。

## 启动链

```text
ABL → UEFI / UniXNU → DarwinBoot → SHENG ARM64E XNU
    → UFS / APFS BaseSystem → dyld → launchd → Recovery 服务
```

临时启动使用 `fastboot boot`，不是把实验内核刷入日常 Android 启动分区。
DarwinBoot 按 16 KiB 页表要求准备映像，内核 VA/PA 的低 25 位必须同余。
根卷位于独立 macosroot 分区，ISC 使用现有实验角色卷；日志写入专用 macoslog 文件。
设备布局和已通过范围见[构建与设备操作](bringup.md)及[移植状态](status.md)。

## 平台选择

25F71 的 M1/T8103 输入用于配套组件和 ABI 参考；SHENG 使用原生平台实现。
M1 不在配套源码的 SPTM 启用列表中，但仍包含 Apple CPU、驱动和安全组件依赖，不能直接运行原版内核。
Neo/T8140 和 VMAPPLE 保留为对照，不作为已支持的 sheng 机型。

| 参考项目 | 可复用内容 | 当前边界 |
| --- | --- | --- |
| UniXNU | sheng 的 UEFI、EL1 平台、UFS、显示及构建实现 | 旧内核 ABI 与 25F71 不同，需要配套适配 |
| Snapintosh | 组件加载、PAC 域、启动日志与驱动依赖的实现思路 | 固定版本依赖 EL2/NV2 监控层，不能在当前 EL1 直接部署 |
| DroidVM | 配套组件、用户态诊断、帧交换和软件显示路径 | 虚拟存储、VirtIO 输入和宿主 GPU 桥不等于 sheng 物理驱动 |

当前没有取得真实 EL2 控制权，也没有实机证据把某次停顿归因于 Gunyah。
不能通过删除 XNU 组件、启动 UEFI 应用或更换 GBL 宣称已关闭 Gunyah。
边界与寄存器陷入对照见[EL1 适配边界](native-el1-boundary.md)。

## 已跨过的阶段与下一项

16 KiB 页表、高位代码执行、基础 PAC 密钥访问、配套内核、原版用户态和实机根卷挂载均已有对应运行证据。
当前阻断位于显示初始化后的物理地址转换；具体候选、panic 和修正见[当前状态](status.md)。
这些结果不代表全部 PAC 生命周期、图形 Recovery 或日常桌面已经验收。
原始路线比较及固件入口调查见[历史记录](history/routes-20261026.md)。

源码依据：[配套 XNU 平台配置](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/makedefs/MakeInc.def)、
[Snapintosh 固定启动链](https://github.com/Snapintosh/Snapintosh/blob/2c60b47a950f6d98caed6b2551adc227f8ced4c9/docs/BOOT-CHAIN.md)。
