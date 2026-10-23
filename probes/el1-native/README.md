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

实机先停在 MMU 实验前，按键后执行；返回后再次停留，下一次按键才执行 PAC 实验。
MMU 实验使用临时 EL1 异常向量，异常时恢复固件页表并显示阶段、ESR/FAR/ELR。
QEMU 另有真实未定义指令控制，确认异常被记录、原有映射恢复且后续 PAC 实验仍可执行。

实机已确认进入 EL1，并收到电源键 Enter，随后停在 `MMU probe starting`。
为区分具体切换位置，屏幕中央的 `0-F` 标签下由汇编直接填绿色格子，刷新到显示内存后再继续。
标签及显示区域在固件页表下准备，并检查该区域在实验地址窗口内恒等映射。
MMU 临时状态期间不调用 UEFI、串口或其他驱动。

| 标记 | 已执行到的位置 |
| --- | --- |
| 0 | 进入汇编并保存通用寄存器 |
| 1 | 屏蔽中断，安装临时异常向量 |
| 2 | 第一次关闭 MMU |
| 3 | 安装 4K 控制页表并完成 TLB 维护 |
| 4 | 启用 4K 控制映射 |
| 5 | 完成 4K 有效翻译 A |
| 6 | 完成 4K 空叶翻译 B |
| 7 | 完成 4K 区分地址翻译 C |
| 8 | 为切换 16K 再次关闭 MMU |
| 9 | 设置 16K TCR 并完成 TLB 维护 |
| A | 启用 16K 映射 |
| B | 完成 16K 区分地址翻译 D |
| C | 开始恢复，关闭实验映射 |
| D | 恢复原 TTBR0/TCR/MAIR 并完成 TLB 维护 |
| E | 恢复原 SCTLR |
| F | 恢复原异常向量、PAR 和 PAN，即将返回 |

异常恢复路径可跳过若干中间标记并继续 C-F，不能仅凭出现 F 就认定 16K 成功。
QEMU 同时检查各像素格与负对照/注入异常时的跳过位置；实机仍以实际画面和返回值为准。

实机首次标记停在绿色 0/1/2，尚未完成 4K 控制页表安装。
已按该固件 ArmMmuLib 的实现设置有效 `TG1=4K`，并在 TCR/MAIR 控制更新后先执行 ISB 再维护 TLB。
该固件明确保留 TG1 编码，即便 EPD1 已禁用高地址遍历；不能把旧探针停顿直接归因为 16K 不支持。
标记 3 在这一段细分为：白色表示已写 TTBR0，灰色表示已写 MAIR，紫色表示 TCR 写入及 ISB 已经过，
红色或蓝色表示 TLBI 已发出，绿色才表示后续屏障和安装阶段完成。红/蓝取决于 GOP 像素格式。
这些中间颜色只表示指令已执行到对应位置，不代替最终屏障完成和 A-D 翻译结果。

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
