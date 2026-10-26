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
| 输入 | VirtIO HID 已用于选择语言 | 触控和 USB HID 未验收 |
| 图形加速 | 当前显示路径由 CPU 复制 | Adreno 740 加速驱动尚未实现 |

QEMU 语言选择器结果来自构建 40305570169。
构建 40319163123 在 QEMU 完成首次帧复制，结束时画面为黑底等待指针；该次运行没有重复语言选择器验收。
KDP 实机双向轮询传输、Apple 激活、系统安装和日常桌面使用尚未验收。

## 最新测试候选

| 项目 | 记录 |
| --- | --- |
| 内核 UUID | `2DDC876A-3B4C-3478-8B21-556B7E879EB0` |
| 构建 | [40326900585](https://github.com/CrossDarwin/macOS-ForSheng/actions/runs/40326900585)，内核、UFS、GOP 和输入组件编译成功 |
| 菜单入口 | `UFS+ISC+LOG+UI+QR 2DDC876A` |
| 修改 | 高位物理地址转换修正、首次 panic 二维码 |
| 部署方式 | 临时 `fastboot boot`，复用已有固件、设备树和根卷 |
| 已取得结果 | 临时启动并读回匹配 UUID 的日志，屏幕停在 `Display on` |
| 当前阻断 | WindowServer 崩溃，未记录首次交换和首帧 |

该候选产物的反汇编已确认地址移位使用 64 位寄存器。
独立 ARM64 测试已从实际帧缓冲像素解码二维码，载荷与首次 panic 消息一致。
本次没有重复完整 QEMU 用户态和语言选择器测试，已有其他内核的运行记录保持原归属。

## 实机日志与当前阻断

2DDC876A 的照片显示 `Display on` 停留 503 秒，WindowServer 的启动与退出计数分别为 3、2。
尚未记录 `First swap`、`First frame` 或语言选择器画面，照片未见内核 panic。

Android Recovery 只读读回的两个有效日志槽为 149、150，均匹配本次 UUID。
最新快照累计接收 212,836 字节，保留 81,920 字节，环形覆盖遗漏 130,916 字节，
另有 11,245 字节字符 writer 忙时丢失。文件外区域及保护块与前次读回一致。

保留文本包含 PID 131 的 WindowServer 崩溃通知，但没有原始异常代码或回溯。
源码中的 `Too many corpses being created` 出现在崩溃信息保存失败之后，不能据此确定原始原因。
下一项取证使用默认关闭的 `sheng-windowserver-stop=1`，在目标异常交付前保存用户态现场；
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
