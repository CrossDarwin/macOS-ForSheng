# sheng 原生 EL1 执行探针

用于推进 macOS 26 原生路线的两个未确认条件，不加载 XNU 或系统卷。

`native.S` 由 UEFI 应用和 QEMU 控制共同调用。页表实验借用 Snapintosh 的
`probes/tgran16.c` 区分方法：4K 有效、4K 空叶、4K 区分地址和 16K 区分地址。
此处在 EL1 执行，不能直接采用上游修改 EL1 寄存器的 EL2 调用环境。

执行代码、栈与结果必须位于 2 GiB 至 64 GiB 的恒等映射。
临时表在 4K 和 16K 两种解释下均保持该执行区可用，区分地址为 `0x2001000`。
16K 应翻译到 `0x4001000`，4K 应产生翻译错误；4K 回退不会被误判为 16K 成功。
临时映射只供本核短时实验，期间屏蔽异常中断，不调用固件服务，返回前恢复原有 MMU 状态。
这只验证 36 位实验地址空间的 16K 执行，不证明 macOS 的完整 47 位布局已可用。

PAC 实验保存当前五类密钥，依次安装两组测试密钥，检查 IA/IB/DA/DB 的签名认证、
两组签名差异及 GA 重装后的确定性。原始密钥恢复后读回，栈内副本清除。
测试常量仅用于探针，不进入后续内核的密钥派生。
此实验不证明 XNU 的 task/thread 密钥生命周期、异常返回或 arm64e 用户空间已接通。

构建 UEFI 应用：

```sh
bash scripts/build_preflight.sh --native-el1
```

实际执行同一汇编的 QEMU 正/负对照：

```sh
python3 scripts/test_el1_native.py --clang /path/to/clang --qemu /path/to/qemu-system-aarch64
```

打包沿用已实机成功的 UniXNU 固件、原始厂商 DTB 与当前槽 OS 元数据，使用 RAM FAT。
`scripts/package_el1_native.py --help` 列出输入；该脚本不部署设备。
sheng 当前固件从 RAM FAT 加载该 EFI 时返回 Access Denied；实机使用
`scripts/build_firmware.py --native-el1` 将探针嵌入 FV，由现有注册器直接选择。
该模式不修改全局镜像认证策略，也不使用另一个独立 EFI 构建的哈希替代 FV 内的应用。

参考：[Snapintosh 页粒度实验](https://github.com/Snapintosh/Snapintosh/blob/2c60b47a950f6d98caed6b2551adc227f8ced4c9/probes/tgran16.c)、
[PAC 切换语义](https://github.com/Snapintosh/Snapintosh/blob/2c60b47a950f6d98caed6b2551adc227f8ced4c9/compat/pauth-switch.S)。
