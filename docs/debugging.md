# 日志与崩溃诊断

本页说明 sheng 原生 XNU 的屏幕日志、macoslog 快照和崩溃取证边界。
当前实机结果见[移植状态](status.md)。用户照片、录像、原始日志和内存快照仅保存到本地 `private/`。

## 日志来源

| 来源 | 保存内容 | 限制 |
| --- | --- | --- |
| 滚动控制台 | 当前字符输出 | 屏幕会滚动，刷屏不等于启动推进 |
| 底部进度 | 固定阶段、目标服务、停留时间和提交状态 | 不是百分比，不判定死循环 |
| 首次 panic 面板 | 最多 4,095 字节的首次 panic 文本 | 可见范围受屏幕尺寸限制 |
| panic 二维码 | 内核 UUID、调用地址、钩子寄存器、丢失计数及有界原因 | 仅摘要；实现与实测状态见[二维码说明](panic-qr.md) |
| RAM 保留日志 | 128 字节头、16 KiB 前缀、64 KiB 环形尾部 | writer 忙时会丢字，环形尾部会覆盖旧记录 |
| macoslog 文件 | 定期提交的 RAM 日志快照 | 不保存无限历史，不保证最后时刻或最终 panic |

`LOG committed` 只说明一次提交成功。panic 发生后，工作线程、调度器或存储驱动未必能继续运行。
因此屏幕已有 panic 而磁盘没有对应文本并不矛盾；不能从最后一次快照推断具体停止时刻。
普通字符 writer、首次 panic 文本和 panic 像素区分别管理。普通 writer 忙时，首次 panic 仍可显示。

RAM 头的 `panic_state=3` 表示首次 EL1 同步异常，可能来自此前可恢复的异常。
该记录不会被后续 panic 覆盖，不能把它的 PC/FAR 当作最终 panic 的现场。
二维码单独记录 panic 钩子当时的寄存器，仍不等于原始异常的完整寄存器和调用栈。

## macoslog 写入方式

当前布局由 `config/macoslog.json` 固定：64 MiB FAT16 分区，标签 `MACOSLOG`，
PARTUUID 为 `4cd2ed34-2142-4ea4-abf2-ec6c51d117d7`。
`SHENGLOG.BIN` 为预分配的连续 2 MiB 文件，包含两个 1 MiB 提交槽及文件归属保护块。

`native-ufs-macoslog=2` 启用工作线程。线程核对 GPT、分区身份、FAT 链和保护范围后，
每 2 秒尝试保存变化后的日志，先写数据，再提交带 CRC 的头部。
内核只更新既有文件的数据区，不新建文件、不修改 FAT 或 GPT。
任一身份或范围不匹配时停止写入，不转向其他分区。

解码器按内核 UUID、文件标记、CRC 和代数选择有效槽。
`omitted` 表示环形覆盖后无法恢复的字符范围；`dropped` 表示 writer 忙时丢失的字节。
两项为零也只覆盖这次快照，不能证明完整运行历史或最终 panic 已保存。

## 从 Android Recovery 导出

设备需处于已验证的 root Android Recovery，电脑需有 ADB。
以下命令从已核对的 `macoslog` 读取固定 64 MiB，不挂载、不写入，也不自动重启。
`DEVICE_SERIAL`、`CAPTURE` 和 `KERNEL_UUID` 必须替换为本次设备、未使用的捕获名称和实际内核 UUID。

1. 确认设备及分区身份：

   ```sh
   adb devices -l
   adb -s DEVICE_SERIAL shell 'readlink -f /dev/block/by-name/macoslog; blockdev --getsize64 /dev/block/by-name/macoslog'
   ```

   本项目已配置设备的分区为 `sde78`，尺寸应为 `67108864`。
   名称或尺寸不符时停止，核对 GPT，不改用其他块设备。

2. 读取原始分区。目标目录必须不存在：

   ```sh
   mkdir private/device/CAPTURE
   adb -s DEVICE_SERIAL exec-out \
     'dd if=/dev/block/by-name/macoslog bs=4096 count=16384 status=none' \
     > private/device/CAPTURE/macoslog.img
   ```

3. 在仓库根目录解码。脚本会拒绝截断镜像、错误 FAT、保护块、UUID 或提交 CRC：

   ```sh
   PYTHONPATH=scripts python3 - private/device/CAPTURE KERNEL_UUID <<'PY'
   import json
   from pathlib import Path
   import sys
   from native_log_file import FILE_BYTES, decode, locate

   directory, kernel_uuid = Path(sys.argv[1]), sys.argv[2]
   image = (directory / 'macoslog.img').read_bytes()
   offset = locate(image)
   data = image[offset:offset + FILE_BYTES]
   snapshot, report = decode(data, kernel_uuid)
   (directory / 'SHENGLOG.BIN').write_bytes(data)
   (directory / 'console.bin').write_bytes(snapshot)
   (directory / 'console.txt').write_text(report.pop('console_text'))
   (directory / 'console.json').write_text(json.dumps(report, indent=2) + '\n')
   PY
   ```

导出后保留原始分区、二进制、文本、解码元数据及同次内核的 UUID、dSYM、链接 map 和加载地址。
读回后才根据下一次测试需要重启。已有快照槽会被后续运行轮换，不作为归档使用。

## panic 与二维码

出现 `SHENG - FIRST PANIC` 后，拍下完整文字及二维码，不需要继续等待普通进度。
普通扫码软件可读取离线文本，不需要联网或上传照片。
二维码不存放 URL，也不会自动提交报告。编码失败或显示区域不足时保留文字面板。
若屏幕或映射本身损坏，二维码也可能无法绘制。

最终 panic 目前没有同步 UFS 写入路径。不要在 panic 中直接调用依赖工作线程或中断的常规文件系统接口。
Linux DRM panic 的参考机制及本项目编码范围见[panic 二维码](panic-qr.md)。

## 其他调试路径

QEMU 观察器 `scripts/observe_macos26_kernel.py` 可通过 GDB 读取保留日志、寄存器和独立 panic 区。
`scripts/decode_xnu_panic.py` 解码配套 XNU 的 version-8 panic 头，校验 CRC、UUID 和范围。
只使用同次链接的内核及 dSYM，不用原版 T8103 符号代替 SHENG 自构建符号。

内核已包含 KDP 符号，但 sheng 尚无可用的双向轮询收发后端。
ADB 和 fastboot 分别属于 Android 与 ABL，不能充当已停止的 XNU 的 KDP 通道。

旧 DarwinBoot `NEXTLOG.BIN`、`CAPxxxxx` 及 Linux RAM reader 依赖重启后 RAM 保留。
它们没有通过本轮实机捕获验收，不能与已通过的 `SHENGLOG.BIN` 周期写入混为一谈。
实现与失败记录保存在[历史调试记录](history/debugging-before-panic-qr.md)。
