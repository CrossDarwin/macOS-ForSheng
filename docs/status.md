# sheng 移植状态

本文记录 macOS 26.5 / 25F71 在 sheng（SM8550）上的验证结果，更新于 2026-10-27。
内核为配套 XNU 12377.121.6 ARM64E。当前实机目标是显示原版 Recovery 语言选择器。

## 功能状态

| 功能 | QEMU | sheng 实机 |
| --- | --- | --- |
| 内核和用户空间 | 原版 dyld、launchd 和恢复服务已执行 | 原版 launchd 和恢复服务已执行 |
| 根卷和辅助卷 | BaseSystem、ISC 角色卷和临时 Data 已挂载 | UFS 读取、BaseSystem 和 ISC 挂载已通过 |
| 图形 Recovery | 语言选择器已显示，真实输入选中简体中文；后续工具窗口未验收 | 218FDCCE 入口运行后的照片已显示 Language 窗口、许可文字和继续箭头；语言列表为空，选择操作未验收 |
| 日志分区 | 双槽提交、CRC 和保护范围验证通过 | 218FDCCE 匹配快照已读回；本轮字符 writer 忙时丢失为 0，环形尾部仍会覆盖旧记录 |
| panic 二维码 | 实际绘制像素解码通过 | D8D9EDA4 首次 panic 摘要完整读出 |
| 输入 | VirtIO HID 已用于选择语言 | 触控和 USB HID 未验收 |
| 图形加速 | 当前显示路径由 CPU 复制 | Adreno 740 加速驱动尚未实现 |

QEMU 语言选择器结果来自构建 40305570169。
构建 40319163123 在 QEMU 完成首次帧复制，结束时画面为黑底等待指针；该次运行没有重复语言选择器验收。
KDP 实机双向轮询传输、Apple 激活、系统安装和日常桌面使用尚未验收。

## 最近一次实机运行

构建 [40350000836](https://github.com/CrossDarwin/macOS-ForSheng/actions/runs/40350000836) 已通过，
实测 UUID 为 `218FDCCE-86F6-326F-9BC1-536380109D02`，菜单入口为 `UFS+ISC+LOG+UI+REC 218FDCCE`。
临时启动包保留高地址 RAM 写合并修正，包含日志 writer 分离、周期服务清单和恢复组件 stdout/stderr 过滤。
固件、设备树、根卷及分区布局沿用此前配置。本轮通过 `fastboot boot` 临时启动，未刷写启动分区。

照片显示原版 `Language` 窗口、许可文字和继续箭头，列表框内没有可见语言名称。
用户另报告此前出现 Apple 标志加载画面。继续观察后列表仍为空，随后从 uwu Android Recovery 只读导出日志分区。

### 日志读回

`SHENGLOG.BIN` 最新有效槽代数为 383，UUID 匹配本次内核，两槽校验均通过。
快照累计接收 135,016 字节，保留 81,920 字节，环形覆盖遗漏 53,096 字节，字符 writer 忙时丢失为 0。
上一轮 75075C49 的该丢失计数为 144,668；本轮结果确认日志修改在这次实机运行中改善了字符保留，
不代表后续运行必然无丢失，也不代表保存了无限历史或最终 panic。

周期清单记录以下启动与退出事件：

| 组件 | 最后 PID | 启动次数 | 退出次数 |
| --- | --- | --- | --- |
| launchd | 1 | 1 | 0 |
| recoveryosd | 72 | 1 | 0 |
| RecoveryOS Agent | 112 | 1 | 0 |
| WindowServer | 80 | 1 | 0 |
| Language Chooser | 159 | 1 | 0 |

最新保留进度为 `BOOT [##########] - First frame`，没有新阶段或受监测服务事件的时间为 826 秒。
这说明已记录到全部十个进度事件，不代表界面可操作或恢复工具已就绪。
服务清单是事件快照，不是实时线程状态。`lost=19` 还包含周期取锁失败，不能解释为丢失 19 次应用启动。
本次未捕获到恢复组件的 stdout/stderr 文本；统一日志和 syslog 不保证经过这两个接口。

### 当前阻断与恢复工作入口

当前阻断已从没有窗口推进为语言列表持续空白。语言选择操作、恢复工具窗口及实机输入尚未验收。
现有日志不能区分语言数据为空、应用线程等待和列表内容未绘制，不把长期空白只归因于加载缓慢。
配套 Language Chooser 的表格行数来自 `LCAUtilities.languagePrompts`，显示入口会先刷新语言数据，再调用 `reloadData`。
后续需针对该数据及应用线程状态取证，再决定修改位置。

启动耗时尚无完整测量。当前使用 `cpus=1`，由 CPU 复制显示帧；这两项限制不能单独解释本次等待。
ArmCpu 已有受 `sheng-smp` 控制的次级核心注册、PSCI CPU_ON 和 IPI 路径，但当前 macOS 26 实机未完成多核验收。
NativeGOPDisplay 仍明确要求 `cpus=1`，进度面板与图形接管也依赖单核的中断屏蔽边界。
启用多核需要同时验证次级核心、定时器、跨核中断及显示所有权，不能仅修改启动参数。

本轮已保存匹配内核、符号、临时启动包、分区快照和照片。设备停留在 uwu Android Recovery，未开始新的启动测试。
原始取证文件仅保存在本地，不提交仓库或上传 CI。

## 上一轮首帧验证

构建 [40340632440](https://github.com/CrossDarwin/macOS-ForSheng/actions/runs/40340632440) 的实测 UUID 为
`75075C49-498A-3EE2-A304-F0FBBD6BE7A5`，菜单入口为 `UFS+ISC+LOG+UI+RAM 75075C49`。
该次已显示鼠标指针，但没有恢复窗口。最新有效快照代数为 218，累计接收 87,527 字节，
保留 81,920 字节，环形覆盖遗漏 5,607 字节，字符 writer 忙时丢失 144,668 字节。
快照记录首次帧复制及 RecoveryOS Agent 执行；没有 Language Chooser 执行行不能用来断言进程未启动。

后续将 RAM 日志 writer 与普通写屏锁分离，RAM 追加和快照复制期间保存并恢复异步异常屏蔽状态，
并增加全部十个受监测服务的周期快照及 `sheng-stderr-name=recovery-ui` 精确过滤。
独立 ARM64 检查已覆盖屏幕锁占用期间的 RAM 追加、快照、DAIF 恢复、首次 panic 和二维码像素解码。
本轮 218FDCCE 的日志读回结果见上文。

## 此前 WindowServer 异常取证

| 项目 | 记录 |
| --- | --- |
| 内核 UUID | `D8D9EDA4-EC94-3EBB-A60F-FD64D818760F` |
| 构建 | [40332670337](https://github.com/CrossDarwin/macOS-ForSheng/actions/runs/40332670337)，内核及配套驱动编译成功 |
| 菜单入口 | `UFS+ISC+LOG+UI+WS D8D9EDA4` |
| 目的 | 保存 WindowServer 的首个异常或崩溃通知现场 |
| 参数 | 显式开启 `sheng-windowserver-stop=1` |
| 部署方式 | 已封装临时启动包，复用已有固件、设备树和根卷 |
| 实机结果 | 已临时启动；二维码完整读出 WindowServer 的 EL0 对齐异常 |

定向停机代码的主机检查覆盖默认关闭、进程名精确匹配、保存状态缺失及重复调用。
检查直接执行应用补丁后的辅助函数，未代替完整内核运行。
启用该参数后，目标异常交付前会主动 panic；这属于取证流程，尚未修复 WindowServer。
本次实机二维码已离线读出，`TRUNCATED=0`。没有重复完整 QEMU 用户态及语言选择器测试。

## 此前对齐异常

D8D9EDA4 的二维码记录 `SHENG WS EXCEPTION`：PID 80，异常类型 `1`，代码 `0x101`，
用户态 `PC=0x18c3691b4`、`LR=0x192ea3e40`、`ESR=0x92000061`、`FAR=0x10b6e7108`。
配套 XNU 将 `0x101` 定义为 `EXC_ARM_DA_ALIGN`；该 ESR 表示来自 EL0 的写入对齐错误。
这些字段取自保存的用户态状态，不使用二维码通用字段中的 panic 钩子寄存器替代。

对配套共享缓存按 4 KiB 步长检索允许的偏移范围，与填充调用路径一致的偏移候选为 `0x0bedc000`。
此时 PC 位于 `__platform_memset_pattern4` 使用的公共代码块，指令为 `stp q0, q1, [x0]`；
LR 对应 CoreGraphics 的 `_CGBlt_fillBytes` 调用返回点。
这是结合离线指令和调用目标得到的推断，尚未从实机读取缓存偏移或故障指令。

故障地址按 8 字节对齐，但未按 16 字节对齐。
是否由 `SCTLR_EL1.A` 或 Device 类型映射触发，仍需运行时证据。
已增加针对该异常的指令、缓存偏移和地址转换取证。
字段及边界见[WindowServer 对齐取证](debugging.md#windowserver-对齐取证)。

Android Recovery 已只读导出匹配 D8D9EDA4 的最新有效快照，代数为 178。
快照保留累计接收的 66,763 字节，环形覆盖遗漏为 0，字符 writer 忙时丢失为 3,103 字节。
快照未包含最后的主动停机；该现场由本次二维码补充。

### 高地址 RAM 的写合并映射

该启动包的设备树声明 `dram-base=0x80000000`、`dram-size=0x200000000`，
没有覆盖该次分配给 XNU 的高地址 RAM 窗口，物理基址为 `0x8c1004000`。
`wimg_to_pte()` 原先仅用 `is_dram_addr()` 判断 `VM_WIMG_WCOMB` 的类型，
因此会把该窗口的写合并映射选为 Device-GRE，而非 Normal Non-cacheable。

SHENG 补丁 `0063-native-managed-ram-writecombine.patch` 额外接受 `isphysmem()` 确认的内核管理范围。
修改只作用于 `VM_WIMG_WCOMB`，保留执行禁止位、其他缓存模式和窗口外 MMIO 的原有行为。
该修改没有重写设备树的物理 DRAM 拓扑，不能替代后续对设备树声明的完整修正。

主机检查执行实际补丁后的分支，复现原类型选择，并覆盖窗口边界及 SHENG 关闭时的行为。
该分类错误已从源码和启动包确认；当前 WindowServer 的故障地址是否来自此类映射仍待实测。

## 前次 WindowServer 崩溃通知

上一候选 `2DDC876A-3B4C-3478-8B21-556B7E879EB0` 来自构建 40326900585，已临时启动并由匹配 UUID 的日志确认。
照片显示 `Display on` 停留 503 秒，WindowServer 的启动与退出计数分别为 3、2。
尚未记录 `First swap`、`First frame` 或语言选择器画面，照片未见内核 panic。

Android Recovery 只读读回的两个有效日志槽为 149、150，均匹配本次 UUID。
最新快照累计接收 212,836 字节，保留 81,920 字节，环形覆盖遗漏 130,916 字节，
另有 11,245 字节字符 writer 忙时丢失。文件外区域及保护块与前次读回一致。

保留文本包含 PID 131 的 WindowServer 崩溃通知，但没有原始异常代码或回溯。
源码中的 `Too many corpses being created` 出现在崩溃信息保存失败之后，不能据此确定原始原因。
后续 D8D9EDA4 已通过默认关闭的 `sheng-windowserver-stop=1` 保存目标异常现场。
该开关的行为和限制见[WindowServer 异常停机](debugging.md#windowserver-异常停机)。

## 此前的物理地址 panic

候选 UUID 为 `0CF06C86-6A75-3360-99B8-1B1ADFB87ECD`，来自构建 40319163123。
该次运行启用 UFS、ISC、GOP、日志和启动进度诊断，屏幕先记录 `Recovery exec`，随后记录 `Display on`。
WindowServer 格子仍为 `-`，表示该事件未被诊断器记录。
最后屏幕中的 panic 为：

```text
phystokv_range: illegal PA: 0x169b0000
phys base 0x8c1004000, size 0xc0000000
@arm_vm_init.c:418
```

Android Recovery 只读导出的两个有效日志槽代数为 105、106，均匹配该内核 UUID。
最新快照保留 80,037 字节，环形覆盖遗漏为 0，字符 writer 忙时丢失为 3,537 字节。
文件外区域、FAT 和保护块与预分配镜像一致，快照未包含最终 panic。
原始照片、分区镜像及解码记录仅保存在本地 `private/`。

## 地址转换问题与修正

配套源码的 `pmap_sync_page_attributes_phys()` 对 32 位页号执行左移，随后才转换为地址类型。
原表达式会将 `0x9169b0000` 截断为屏幕报错中的 `0x169b0000`。
已接入 UniXNU 的 `zzx-pmap-sync-64bit-pa.patch`，在移位前扩展地址宽度。

现有现场缺少完整回溯，因此该原因与错误地址吻合，但尚未证明是本次 panic 的实际调用路径。
2DDC876A 已运行至用户态 WindowServer 崩溃通知，该次照片和保留日志未见相同地址 panic。
这只说明该次现象没有再次被观察到，仍需针对当前用户态异常定位。

[首次 panic 二维码](panic-qr.md)保存有界摘要，不包含完整日志或调用栈。
磁盘周期快照也不保证最终 panic、完整运行历史或跨重启 RAM 保留，取证方法见[日志与崩溃诊断](debugging.md)。

此前调查见[历史实施记录](history/status-before-panic-qr.md)。历史记录中的阶段性阻断不作为当前状态。
