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
| 内核 UUID | `D8D9EDA4-EC94-3EBB-A60F-FD64D818760F` |
| 构建 | [40332670337](https://github.com/CrossDarwin/macOS-ForSheng/actions/runs/40332670337)，内核及配套驱动编译成功 |
| 菜单入口 | `UFS+ISC+LOG+UI+WS D8D9EDA4` |
| 目的 | 保存 WindowServer 的首个异常或崩溃通知现场 |
| 参数 | 显式开启 `sheng-windowserver-stop=1` |
| 部署方式 | 已封装临时启动包，复用已有固件、设备树和根卷 |
| 实机结果 | 尚未执行 |

定向停机代码的主机检查覆盖默认关闭、进程名精确匹配、保存状态缺失及重复调用。
检查直接执行应用补丁后的辅助函数，未代替完整内核运行。
启用该参数后，目标异常交付前会主动 panic；这属于取证流程，尚未修复 WindowServer。
已有二维码像素执行证据按相同源码复用，本次没有重复完整 QEMU 用户态及语言选择器测试。

## 实机日志与当前阻断

上一候选 `2DDC876A-3B4C-3478-8B21-556B7E879EB0` 来自构建 40326900585，已临时启动并由匹配 UUID 的日志确认。
照片显示 `Display on` 停留 503 秒，WindowServer 的启动与退出计数分别为 3、2。
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
