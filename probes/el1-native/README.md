# sheng 原生 EL1 执行探针

用于推进 macOS 26 原生路线的两个未确认条件，不加载 XNU 或系统卷。

`native.S` 由 UEFI 应用和 QEMU 控制共同调用。页表实验借用 Snapintosh 的
`probes/tgran16.c` 区分方法：4K 有效、4K 空叶、4K 区分地址和 16K 区分地址。
此处在 EL1 执行，不能直接采用上游修改 EL1 寄存器的 EL2 调用环境。

当前实验只启用固件原本关闭的 TTBR1 高地址窗口，TTBR0/TG0、MAIR 和 SCTLR 不变。
高地址样本的低 36 位为 `0x1000` 和 `0x2001000`，由 `AT S1E1R` 执行实际硬件遍历。
16K 区分地址应翻译到 `0x4001000`，4K 应产生翻译错误。
实验不跳转到高地址，不读取翻译出的假定物理地址，也不关闭固件 MMU。
这只证明 36 位临时窗口的页表遍历，不证明完整 47 位映射或 16K 内核代码已能执行。

入口要求 TTBR1 遍历已禁用、ASID 来自 TTBR0、SP_EL1 被选用，并存在 Normal WB 的 MAIR 槽。
叶描述符复用该槽，不能假定槽 0 是正常内存；sheng 记录中的槽 3 为 `0xff`。
页表必须为 16 KiB 对齐的恒等映射内存；实验使用本核 TLB 维护，返回前恢复 TTBR1/TCR/PAR/异常向量及中断状态。
切换 TG1 前先禁用临时遍历并清除翻译，避免更改固件执行区的页粒度。

PAC 实验保存当前五类密钥，依次安装两组测试密钥，检查 IA/IB/DA/DB 的签名认证、
两组签名差异及 GA 重装后的确定性。原始密钥恢复后读回，栈内副本清除。
测试常量仅用于探针，不进入后续内核的密钥派生。
此实验不证明 XNU 的 task/thread 密钥生命周期、异常返回或 arm64e 用户空间已接通。

实机先停在 MMU 实验前，按键执行后再停留，下一次按键才执行 PAC 实验。
临时 EL1 异常向量在保留的固件映射下执行，异常时恢复原 TTBR1/TCR 并显示阶段、ESR/FAR/ELR。
QEMU 正对照、强制 4K 回退负对照和真实未定义指令恢复均使用同一份汇编。
控制环境保留 M/C/I 开启，并采用 sheng 观察到的 `MAIR=0xffbb4400`，检查 MAIR 槽 3 和固件状态恢复。

屏幕中央 `0-F` 标签下由汇编填绿色格子；MMU 实验期间不调用 UEFI、串口或驱动。

| 标记 | 已执行到的位置 |
| --- | --- |
| 0 | 进入汇编并保存通用寄存器 |
| 1 | 屏蔽中断，安装临时异常向量 |
| 2 | 安装临时 TTBR1，遍历仍禁用 |
| 3 | 启用高地址 4K 控制窗口并完成屏障 |
| 4 | 完成 4K 有效翻译 A |
| 5 | 完成 4K 空叶翻译 B |
| 6 | 完成 4K 区分地址翻译 C |
| 7 | 禁用临时窗口并清除旧翻译 |
| 8 | 设置 TG1=16K，遍历仍禁用 |
| 9 | 启用 16K 窗口并完成屏障 |
| A | 完成 16K 区分地址翻译 D |
| B | 开始恢复，禁用临时窗口并清除翻译 |
| C | 恢复原 TTBR1 |
| D | 恢复原 TCR 并完成 TLB 维护 |
| E | 恢复原异常向量、PAR 和 PAN |
| F | 即将恢复中断并返回 |

异常路径可跳过中间标记并继续 B-F；只有 A-D 控制结果及原状态恢复全部正确才能报告成功。

此前替换 TTBR0 并关闭 MMU 的实验只显示完整 0/1，2 只有细线，3 未亮。
关闭 MMU 后的显示标记没有可见地完成，不能由此断言 TTBR 写入失败或 16K 不支持。
当前改用闲置 TTBR1，去掉这项对执行和显示映射的干扰；尚待 sheng 实机结果。

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
