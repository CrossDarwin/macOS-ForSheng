# macOS-ForSheng

小米平板 6S Pro（sheng / SM8550）的 macOS 移植研究项目。
目标系统为 macOS 26.5 / 25F71，使用配套 XNU 12377.121.6 ARM64E、恢复系统和用户空间。
仓库：[CrossDarwin/macOS-ForSheng](https://github.com/CrossDarwin/macOS-ForSheng)。

项目尚未正式对外发布。第三方宣传不代表项目声明。

## 当前状态

sheng 已从 UFS 挂载 BaseSystem，执行原版 launchd 及恢复服务，并将日志快照写入 macoslog。
最近一次实测到达显示开屏事件，随后因物理地址转换 panic 停止；修正待实机验证。
QEMU 已显示原版语言选择器并选中简体中文，该结果不代表 sheng 已显示图形 Recovery。
实机触控、USB 输入、GPU 加速和系统安装尚未验收。

## 开发文档

- [实施状态与当前阻断](docs/status.md)
- [构建与设备操作](docs/bringup.md)
- [日志导出与崩溃诊断](docs/debugging.md)
- [固定阶段进度条](docs/boot-progress.md)
- [首次 panic 二维码](docs/panic-qr.md)
- [原生 EL1 启动路线](docs/routes.md)
- [PAC 与安全组件](docs/macos26-security.md)
- [DroidVM 显示与用户态参考](docs/droidvm-reference.md)

源码提交固定在 `sources.lock.json` 和 `config/macos26-sources.json`。
Apple 系统输入及配对约束见 `config/macos26.json`，构建入口见手动工作流 `.github/workflows/bringup.yml`。
上游源码、Apple 输入、设备备份、照片、录像和原始日志不纳入 Git。
旧 `xnu/` 与 `config/guest.json` 分别保留早期内核和 macOS 27 的参考输入，不能替代当前配套系统。

## 许可

项目原创工具、测试、配置和文档默认采用 [GPL-3.0-or-later](LICENSE)，允许商用。
分发修改版时须遵守对应源码提供及版权、许可证声明保留要求。
内核辅助代码、固件探针和第三方代码保留各自许可，范围与来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
