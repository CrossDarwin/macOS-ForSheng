# EL1 多核启动

多核开发复用 UniXNU 的 ArmCpu、PSCI 和 GICv3 路径。
当前 QEMU 八核已执行到真实 `launchd main`，八核均收到定时器和核间中断。
实机和图形多核仍待验证。

## 上游配置

[UniXNU-sheng 板级配置](https://github.com/UniXNU/UniXNU-sheng/blob/2b7a5815110bf75713eb596612b0b33231b181f8/board.toml)
列出 `0,0x100,0x200,0x300,0x400,0x500,0x600,0x700` 八个核心，使用 SMC 形式的 PSCI。
`sheng-smp=1` 启动次级核心，`armcpu-spi-ipi=1` 使用分配给各核的 SPI 发送核间中断。

[复位补丁](https://github.com/UniXNU/UniXNU/blob/fb6aad6ab1f50199a4d99d2da1d0ca403b067633/patches/xnu/native-smp-secondary.patch)
保留 MPIDR 低 16 位，覆盖 SM8550 在 Affinity1 中的核心编号。
配套 macOS 26 内核使用 `SHENG` 条件接入相同处理。

ARM64E 还需在次级核心进入 C 代码前安装启动核的 PAC 密钥。
启动核在初始化数据段中保存密钥；ArmCpu 在 `CPU_ON` 前清理对应缓存行，次级核心在开启地址转换前恢复密钥。
日志不输出密钥内容。

## QEMU 观察

`scripts/observe_macos26_kernel.py` 的 `--smp` 可取 `1`、`2`、`4`、`8`。
沿用配套内核、固件和检查点参数，增加 `--smp 2` 即可请求双核观察。
观察器同步设置 QEMU 核数、设备树和内核参数，并开启自发 IPI。
QEMU 使用 SGI；实机使用的 SPI 路径需另行验证。

构建 40949503078 的八核运行已到达 `load_init_program`。七个副核均完成初始化，
PSCI 返回值与失败计数均为 0，八核均收到定时器中断。
该次发送 8 次自发 IPI，接收计数为 0；不能据此认定跨核调度可用。

反汇编确认该构建的 `signalCPU` 缺少 SGI 寄存器写入。
Mach-O 汇编将行内分号作为注释，导致同一行后续指令被丢弃。
修正将 ArmCpu 多指令汇编改为换行，并修正 SGI 探针的输入、输出操作数。
构建时检查实际目标文件，要求发送函数和探针保留 `ICC_SGI1R_EL1` 写入与后续 `ISB`。
修正构建 [40952990576](https://github.com/CrossDarwin/macOS-ForSheng/actions/runs/40952990576) 已通过。
八核运行到达真实 `launchd main`，第一条指令已执行，随后继续至 180 秒取证时限。
七个副核均完成初始化，PSCI 返回值和失败计数均为 0。
最终八核的定时器计数均非零，IPI 接收计数为 `7366,7307,7078,6059,5883,6070,5407,5698`。
该运行未启用 GOP 图形输出，也未验证特定线程的跨核迁移或性能提升。

`result.json` 的 `smp_runtime` 记录各核启动阶段、PSCI 返回值、实际 affinity、定时器及 IPI 计数。
`secondary_init_complete` 表示所有请求的次级核心进入 ArmCpu 的运行状态。
`all_cores_received_timer` 和 `all_cores_received_ipi` 分别记录两类中断的逐核到达情况，
`all_cores_received_timer_and_ipi` 表示两项均满足。空闲核的定时器计数可保持为零，需结合实际工作负载判断。
调度迁移仍需运行验证。

## QEMU 时序诊断

TCG 多核观察可增加 `--qemu-smp-timeouts`。
该选项将中断延迟检查设为记录模式，并把普通锁、ticket 锁超时设为 1 秒。
它通过 `interrupt-masked-debug-mode=1`、`slto_us=1000000` 和 `tlto_us=1000000` 接入原有 XNU 参数。

XNU 在中断延迟检查处于 panic 模式时，会用其中断关闭阈值限制锁等待时间。
因此，仅提高锁超时不能排除 TCG 和调试停顿引起的时序影响。
该选项仅作用于 QEMU 观察器；实机参数保持原样。

## 多核图形候选

新候选允许 `--smp 8 --native-gop-display`。增加 `--boot-progress` 可同时采集阶段、服务和逐核计数。内核和 GOP companion 必须使用同一版写屏所有权契约；
缺少配套 PAC、写屏锁或 panic 重绘补丁时，观察器拒绝多核图形组合。

GOP 与诊断面板按扫描线互斥写屏。panic 立即接管显示，停住其他核后重绘首次文字和二维码。
启动条与逐核计数的使用方式见[启动进度诊断](boot-progress.md)。

当前已完成 ARM64 panic 像素解码、八线程互斥、计数和滚屏竞争边界测试。
构建 41002348509 的越界滚屏问题已修正；该旧版禁止部署。
修正构建 [41008552166](https://github.com/CrossDarwin/macOS-ForSheng/actions/runs/41008552166) 在八核、进度条开启的 QEMU 中完成 180 秒观察。
真实 `launchd main` 已执行，`recoveryosd`、`WindowServer` 和 `coreservicesd` 已启动，八核 timer、IPI 均增长，未观察到致命 panic。
该轮使用 VirtIO 文字输出与 QEMU 时序诊断参数；实机多核图形尚未验收。
当前实验分区布局见[重新安装实验环境](status.md#重新安装实验环境)。
