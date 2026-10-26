# 启动进度诊断

启动进度诊断在滚动日志下方显示固定阶段、服务事件和日志提交状态。
它根据实际记录的事件更新，适用于 `cpus=1` 的启动调试。

## 启用诊断

在已启用屏幕控制台的候选中添加 `sheng-boot-progress=1`。未指定时关闭。
封装器 `scripts/package_macos26_ufs.py` 的 `--boot-progress` 选项同时启用有界 WindowServer 输出采集。

以下为字段格式示例，不是某次设备运行记录：

```text
BOOT [#####-#---] - WindowServer exec
No new stage/service: 60s - no loop verdict
WindowServer pid=85 starts=2 exits=1 wait-status=256
LOG committed gen=73 bytes=59551 drops=0 error=0 lost=0
```

## 阶段格

十个格子从左到右固定对应下表。`#` 表示事件已记录，`-` 表示尚未记录。
位图只设置、不清除；后面的阶段先出现时，中间可以保留 `-`。
事件竞争丢失也会留下空格，因此缺格本身不能证明某个进程没有执行。

| 位置 | 屏幕名称 | 记录条件 |
| --- | --- | --- |
| 0 | `Kernel` | 内核到达控制台创建路径 |
| 1 | `VM ready` | VM 初始化后到达控制台创建路径 |
| 2 | `IOKit entry` | 进入 `PE_lockdown_iokit` |
| 3 | `Root mounted` | `vfs_mountroot` 成功返回 |
| 4 | `launchd exec` | 装载 launchd 映像 |
| 5 | `Recovery exec` | 装载 recoveryosd 或 RecoveryOS Agent 映像 |
| 6 | `WindowServer exec` | 装载 WindowServer 映像 |
| 7 | `Display on` | 原版帧缓冲队列完成开屏通知 |
| 8 | `First swap` | 首次交换请求进入驱动验证路径 |
| 9 | `First frame` | 驱动完成首帧 CPU 复制和写入屏障 |

这些条件分别覆盖路径入口、映像装载和显示交换。进程映像装载后仍需执行初始化，
首帧复制后仍需检查图像内容；语言选择器显示结果单独记录在[移植状态](status.md)。

## 服务和停留时间

新阶段或首次出现的目标服务会更新最后进展时间。重复阶段、普通日志和同名服务重启不重置该时间。
底部服务行显示最近记录的目标服务，以及以下字段：

| 字段 | 含义 |
| --- | --- |
| `pid` | 最近一次已记录启动的 PID |
| `starts` | 该服务已记录的启动次数 |
| `exits` | 该服务已记录的退出次数 |
| `wait-status` | 当前记录的原始 wait status，新进程启动时清零 |

新启动后的 `wait-status=0` 不能单独解释为正常退出。旧 PID 的退出不会覆盖新实例状态。目标范围包括 launchd、recoveryosd、RecoveryOS Agent、
WindowServer、Language Chooser、Recovery Springboard、lsd、coreservicesd、loginwindow 和 diskarbitrationd。
进程名按内核短名称匹配，屏幕中的 `Recovery Springb` 对应 Recovery Springboard。

根卷成功挂载后，独立线程每 2 秒刷新一次停留时间；早期时钟未就绪时返回 0。
新阶段立即写入进度摘要，未变化状态每 30 秒补写一次。
线程无法调度或内核停止时，计时显示也会停止。停留时间只表示没有记录到新进展，不判定死循环。

## 日志提交字段

| 字段 | 含义 |
| --- | --- |
| `LOG` | `off`、`opening`、`verified`、`committed` 或 `stopped` |
| `gen` | 日志工作线程最近一次提交的代数 |
| `bytes` | RAM 字符记录累计接收的字节数 |
| `drops` | 字符 writer 忙时丢失的字节数 |
| `error` | 存储路径返回的错误值 |
| `lost` | 未取得诊断状态写入锁的尝试次数，包含定时刷新 |

`lost` 与 `drops` 来自不同记录路径，前者不能换算成丢失的服务事件数。
`committed` 只确认已有一次磁盘提交。周期快照的格式和导出方式见[日志与崩溃诊断](debugging.md)。

## 显示交接与输出范围

诊断区占用已映射 panic 区的底部四行，与普通滚动日志分开。
发生 panic 时由[首次 panic 面板和二维码](panic-qr.md)覆盖。
第一次图形复制成功后，诊断器停止写入像素；复制失败时恢复诊断区所有权。
单核模式下，每条扫描线短暂屏蔽中断并复查所有权，防止旧诊断刷新覆盖接管后的图形帧。

WindowServer 采集分别覆盖 `write` 和 `writev` 的尝试输出，每次最多记录 159 字节，
向量写入最多检查 16 个 iovec。超限时标注截断，读取用户地址失败时跳过该次诊断。
原写入参数、UIO 游标、错误值和返回值保持原有行为。
该采集范围不包含统一日志数据库或其他任意进程的完整输出。

## 实现位置

状态模型位于 `platform/sheng/macos26/log/boot_progress.h`，内核接入位于同目录的 `boot_progress_kernel.h`。
`process_output.h` 提供有界输出采集。主机状态测试和 ARM64 像素测试分别验证事件语义及显示交接，
各完整内核和实机运行的结果统一记录在[移植状态](status.md)。
