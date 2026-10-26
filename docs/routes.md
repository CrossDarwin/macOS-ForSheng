# 原生 EL1 启动路线

sheng 使用 ABL、UEFI 和 DarwinBoot 临时启动自构建 SHENG ARM64E 内核。
当前交接级别为 EL1，系统输入固定为 macOS 26.5 / 25F71。

## 启动流程

```text
ABL → UEFI / UniXNU → DarwinBoot → SHENG ARM64E XNU
    → UFS / APFS BaseSystem → dyld → launchd → Recovery 服务
```

ABL 通过 `fastboot boot` 接收临时启动容器。UEFI 菜单将所选入口交给 DarwinBoot，
后者准备内核、设备树和引导参数，再进入 SHENG 内核。
16 KiB 引导映射要求内核虚拟地址与物理地址的低 25 位同余。

内核从独立 `macosroot` 根盘窗口读取 BaseSystem，使用实验 ISC 角色卷建立恢复环境。
周期日志写入专用 `macoslog` 文件。磁盘布局见[构建与设备操作](bringup.md)。

## 系统与平台配对

25F71 M1/T8103 输入提供配套组件和 ABI 参考，SHENG 提供 sheng 的原生平台实现。
M1 未列入配套源码的 SPTM 启用集合，但仍包含 Apple CPU、驱动和安全组件依赖。
Neo/T8140、VMAPPLE 及旧 iPadOS 内核保留用于对照，当前加载链统一使用配套的 25F71 内核和用户空间。

源码中的平台集合见[配套 XNU 的 MakeInc.def](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/makedefs/MakeInc.def)。
组件与 PAC 处理见[原生安全组件](macos26-security.md)。

## 上游实现的适用范围

| 参考项目 | 采用的机制 | 需要单独适配的部分 |
| --- | --- | --- |
| UniXNU | sheng UEFI、EL1 平台、UFS 和显示实现 | 旧内核与 25F71 的 ABI 差异 |
| Snapintosh | 组件加载、PAC 域、启动日志及驱动依赖处理 | 固定版本依赖的 EL2/NV2 监控层 |
| DroidVM | 用户态诊断、帧交换和 CPU 显示路径 | 物理 UFS、真实输入和原生 GPU 后端 |

当前内核不拥有真实 EL2，Snapintosh 的监控层不能部署到这个 EL1 入口。
其固定版本的依赖见[启动链说明](https://github.com/Snapintosh/Snapintosh/blob/2c60b47a950f6d98caed6b2551adc227f8ced4c9/docs/BOOT-CHAIN.md)。
EL1 可用机制和寄存器陷入对照见[EL1 适配边界](native-el1-boundary.md)，显示适配见[DroidVM 参考](droidvm-reference.md)。

## 验证记录

内核、用户态、根卷和图形结果按候选分别记录在[移植状态](status.md)。
早期页表和基础 PAC 探针只证明对应测试路径，不能替代完整进程生命周期或图形界面的验收。
原始路线比较和固件入口调查见[历史记录](history/routes-20261026.md)。
