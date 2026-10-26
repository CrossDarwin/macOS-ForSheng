# macOS-ForSheng

Repository: [CrossDarwin/macOS-ForSheng](https://github.com/CrossDarwin/macOS-ForSheng)

请注意，这个项目未曾被公开 如果你在 X(推特) 等地方发现了这个项目的宣传 皆为冒假
Please note that this project has never been publicly announced. If you find any promotion for this project on platforms like Twitter, it is a scam.

小米平板 6S Pro（sheng / SM8550）的 macOS 移植研究目录。

当前系统目标为 macOS 26.5 / 25F71，内核、恢复系统和用户空间来自同一构建。
UniXNU 提供 sheng 硬件基线；Snapintosh 作为兼容实现参考，不限定移植路线。

- [开发、构建与设备探测](docs/bringup.md)
- [实施状态与当前阻塞](docs/status.md)
- [完整上游 sheng 配置](config/sheng_defconfig)
- [配置、构建链和输入锁](config/sheng-baseline.json)
- [硬件基线源码提交](sources.lock.json)
- [macOS 26.5 源码提交](config/macos26-sources.json)
- [系统输入与配对约束](config/macos26.json)
- [手动构建工作流](.github/workflows/bringup.yml)

已完成 UEFI 实机探针。当前入口为 EL1，上游 EL2 监控层不能直接部署。
优先研究 M1/T8103 的原生适配，保留 Neo/T8140 与 VMAPPLE 对照。
QEMU已执行原版ARM64E launchd、sh和bash，完成临时Data卷挂载及模板复制，恢复服务开始建立Aqua会话。
原版偏好服务早退及平台UUID超时已修复；WindowServer退出定位到HID与显示初始化。
配套UFS组件的构建、重定位和QEMU默认关闭路径已通过；sheng实际根盘空间、UFS读盘及新版硬件封装仍待验证。
sheng实机尚未验证这些新组件；旧XNU仅用于独立的硬件交接实验。

```sh
python3 scripts/sources.py fetch --group all
python3 scripts/sources.py fetch --lock config/macos26-sources.json --group macos26
python3 scripts/apply_patches.py
python3 scripts/fetch_inputs.py --config config/macos26.json --jobs 8
python3 -m unittest discover -s tests -v
```

上游源码、Apple 输入、设备备份、运行日志和旧研究记录均保持独立并被 Git 忽略。
`xnu/` 保留为 iPadOS 17 参考树，不能替代 macOS 26 的配对内核。
`config/guest.json` 和旧 J700 提取工具保留 macOS 27 / 26A428 的参考合同，不用于当前系统输入。

项目原生工具、测试、配置和文档默认采用 [GPL-3.0-or-later](LICENSE)，允许商用。
分发受 GPL 覆盖的修改版时须遵守对应源码提供、版权与许可证声明保留等要求。
具有独立许可标记的内核辅助代码、固件探针和第三方代码保留原条款；
来源、署名和许可范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
