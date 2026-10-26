# macOS-ForSheng

macOS-ForSheng 是面向小米平板 6S Pro（sheng / SM8550）的原生 macOS 移植项目。
目标系统为 macOS 26.5 / 25F71，使用配套 XNU 12377.121.6 ARM64E、恢复系统和用户空间。
项目通过 UEFI、DarwinBoot 和自构建 SHENG EL1 内核加载系统，硬件适配参考 UniXNU，组件与显示实现参考 Snapintosh 和 DroidVM。

项目当前仍处于实验阶段。已验证功能、当前阻断和实机测试结果见[移植状态](docs/status.md)。
