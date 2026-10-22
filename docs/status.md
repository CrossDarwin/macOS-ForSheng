# 实施状态 - 2026-10-23

目标保持 macOS 27.0 / 26A428，没有降级到 iPadOS 内核。

| 项目 | 状态 |
| --- | --- |
| UniXNU、Snapintosh、q1n1、依赖与两套 Mesa | 已固定提交并获取，补丁保存在本项目 |
| 完整 26A428 IPSW | 下载完成，SHA-256 与 Apple CDN 元数据一致 |
| J700 kernelcache / ADT / SPTM / TXM | 四项哈希与上游客体配置一致 |
| 对应 KDK | 下载哈希通过；签名及内核 UUID 单独由 macOS 工作流验证 |
| ShengPreflight | 本地及 GitHub Actions 编译通过，未在设备 UEFI 执行 |
| 上游 EL2 监控层 | 本地及 xcode-27 Actions 编译通过，仍为 A16 构建基线 |
| 完整 sheng UEFI | 本地构建通过；板级静态检查和 FV 检查通过，未部署 |
| 设备备份 | 六个 LUN 主备 GPT、16 个引导分区已读取并校验，userdata 未备份 |
| macOS 实机启动 / 双系统 | 未实现，未写分区，设备已返回 Android |

## 当前阻塞

Recovery 的实际内核日志确认全部 CPU 从 EL1 启动，KVM 报告 HYP mode not available。
这证明当前 Android/Recovery 交接没有提供可直接使用的 EL2；不证明所有其他固件入口都不可能。
Snapintosh 的现有监控层要求 EL2，因此不能直接放进这条启动链。
EL0 采集到的 ID 寄存器经过 Linux 过滤，NV2 的物理实现与 UEFI 行为测试仍未确认。

原版 J700 内核标识为 Darwin 27.0.0 / XNU 13432.1.9 / T8140。
本次查询 Apple 官方 XNU 仓库，没有找到 xnu-13432 系列标签。
现有 XNU 10063.141.1 是 iPadOS 17 基线，不能作为 macOS 27 的重编译替代。

下一阶段需要验证可用的 EL2 入口，或证明 macOS 27 内核在 EL1 的独立适配方案。
当前没有已验证的替代方案；不会通过伪造 CPU 特性、拼接旧内核或改动分区来宣告进展。
在解决启动路线、完成用户数据备份与恢复验证之前，不实施 96 GiB 分区变更。
