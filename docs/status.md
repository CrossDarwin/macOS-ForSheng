# sheng 移植状态

本文记录 macOS 26.5 / 25F71 在 sheng（SM8550）上的验证结果，更新于 2026-10-26。
内核为配套 XNU 12377.121.6 ARM64E。当前实机目标是显示原版 Recovery 语言选择器。

## 功能状态

| 功能 | QEMU | sheng 实机 |
| --- | --- | --- |
| 内核和用户空间 | 原版 dyld、launchd 和恢复服务已执行 | 原版 launchd 和恢复服务已执行 |
| 根卷和辅助卷 | BaseSystem、ISC 角色卷和临时 Data 已挂载 | UFS 读取、BaseSystem 和 ISC 挂载已通过 |
| 图形 Recovery | 语言选择器已显示，真实输入选中简体中文；后续工具窗口未验收 | 已记录开屏事件，尚无语言选择器画面 |
| 日志分区 | 双槽提交、CRC 和保护范围验证通过 | 双槽读回通过，最近一次最终 panic 未写入 |
| panic 二维码 | 实际绘制像素解码通过 | D8D9EDA4 首次 panic 摘要完整读出 |
| 输入 | VirtIO HID 已用于选择语言 | 触控和 USB HID 未验收 |
| 图形加速 | 当前显示路径由 CPU 复制 | Adreno 740 加速驱动尚未实现 |

QEMU 语言选择器结果来自构建 40305570169。
构建 40319163123 在 QEMU 完成首次帧复制，结束时画面为黑底等待指针；该次运行没有重复语言选择器验收。
KDP 实机双向轮询传输、Apple 激活、系统安装和日常桌面使用尚未验收。

## 最近一次实机取证

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

## 实机日志与当前阻断

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

## 下一次实测候选

构建 [40340632440](https://github.com/CrossDarwin/macOS-ForSheng/actions/runs/40340632440) 已完成内核和配套驱动编译。
候选 UUID 为 `75075C49-498A-3EE2-A304-F0FBBD6BE7A5`，菜单入口为 `UFS+ISC+LOG+UI+RAM 75075C49`。
临时启动包包含高地址 RAM 写合并修正及对齐异常取证，保留现有固件、设备树、根卷和分区布局。

已核对最终链接内核包含管理范围判断、`AT S1E0W` 查询及原有物理地址宽度修正。
16 KiB 页表下的独立查询执行检查覆盖 Normal、Device、只读和未映射地址，并确认 PAR 与 DAIF 恢复。
二维码源码沿用 D8D9EDA4 的实机读取结果，没有重复完整 QEMU 图形启动测试。
该候选尚未实机执行，不能将编译和封装成功作为语言选择器已经显示的证据。

### 前次 WindowServer 崩溃通知

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
