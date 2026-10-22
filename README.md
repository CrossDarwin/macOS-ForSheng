# macOS-ForSheng

小米平板 6S Pro（sheng / SM8550）的 macOS 移植研究目录。

目标固定 macOS 27.0 / 26A428。UniXNU 提供 sheng 硬件基线，Snapintosh 提供 macOS 客体兼容实现。

- [开发、构建与设备探测](docs/bringup.md)
- [实施状态与当前阻塞](docs/status.md)
- [固定源码提交](sources.lock.json)
- [手动构建工作流](.github/workflows/bringup.yml)

已完成源码获取、UEFI 探针与上游监控层编译，以及 J700 引导组件哈希校验。
当前还没有 sheng 上的 macOS 内核启动结果。上游监控层产物仍属于 A16 构建基线，不能直接部署。

```sh
python3 scripts/sources.py fetch --group all
python3 scripts/apply_patches.py
python3 -m unittest discover -s tests -v
```

上游源码、Apple 输入、设备备份、运行日志和旧研究记录均保持独立并被 Git 忽略。
`xnu/` 保留为未修改的 iPadOS 17 参考树，不作为 macOS 27 的内核替代。
