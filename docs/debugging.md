# 日志与崩溃诊断

sheng 原生 XNU 同时提供屏幕诊断、RAM 保留日志和 macoslog 周期快照。
本文说明各来源保存的内容、快照导出方法和崩溃后的读取限制。实测结果见[移植状态](status.md)。

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
磁盘可能只保留崩溃前的快照，最终 panic 的文字需另从屏幕或独立 panic 区取证。
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
以下步骤只读取当前布局中的 64 MiB `macoslog` 分区，不挂载文件系统，也不重启设备。
在仓库根目录执行，并替换这些参数：

| 参数 | 取值 |
| --- | --- |
| `DEVICE_SERIAL` | `adb devices -l` 中的目标设备序列号 |
| `CAPTURE` | 尚不存在的本地捕获目录名 |
| `KERNEL_UUID` | 本次实际选择的内核 UUID |

1. 检查设备及日志分区：

   ```sh
   adb devices -l
   adb -s DEVICE_SERIAL shell 'id -u; getprop ro.product.device; readlink -f /dev/block/by-name/macoslog; blockdev --getsize64 /dev/block/by-name/macoslog'
   ```

   当前实验布局应返回 root 身份、设备 `sheng`、块设备 `sde78` 和尺寸 `67108864`。
   结果不符时先核对设备与 GPT，不改用其他块设备。

2. 读取原始分区。程序以排他方式创建目录和文件，已存在的捕获记录不会被覆盖：

   ```sh
   python3 - DEVICE_SERIAL private/device/CAPTURE <<'PY'
   from pathlib import Path
   import subprocess
   import sys

   serial, directory = sys.argv[1], Path(sys.argv[2])
   directory.mkdir(parents=True, exist_ok=False, mode=0o700)
   image = directory / 'macoslog.img'
   with image.open('xb') as output:
       result = subprocess.run([
           'adb', '-s', serial, 'exec-out',
           'dd if=/dev/block/by-name/macoslog bs=4096 count=16384 status=none',
       ], stdout=output, stderr=subprocess.PIPE, timeout=90)
   (directory / 'capture-stderr.txt').write_bytes(result.stderr)
   result.check_returncode()
   if image.stat().st_size != 67108864:
       raise SystemExit('incomplete macoslog image; partial capture retained')
   PY
   ```

   成功时生成 64 MiB 的 `macoslog.img`。读取失败时保留已有字节及错误输出，使用新目录重新捕获。

3. 解码匹配内核的最新有效槽：

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

解码器拒绝截断镜像、错误 FAT、保护块或无匹配提交的输入。
`console.json` 记录所选槽、代数、内核 UUID 和丢失计数；`console.txt` 只包含该快照中可恢复的文本。
同时保留原始分区、本次内核、dSYM、链接 map 和实际加载地址。
后续启动会轮换日志槽，磁盘快照不能代替本地归档。

## panic 与二维码

出现 `SHENG - FIRST PANIC` 后，拍下完整文字及二维码，不需要继续等待普通进度。
普通扫码软件可读取离线文本，不需要联网或上传照片。
二维码不存放 URL，也不会自动提交报告。编码失败或显示区域不足时保留文字面板。
若屏幕或映射本身损坏，二维码也可能无法绘制。

最终 panic 目前没有同步 UFS 写入路径。现有常规文件系统接口依赖调度或中断，不适用于该崩溃路径。
Linux DRM panic 的参考机制及本项目编码范围见[panic 二维码](panic-qr.md)。

## WindowServer 异常停机

`sheng-windowserver-stop=1` 为定向取证开关，默认关闭。
仅当当前进程短名称精确为 `WindowServer` 时，才在异常交付或当前进程的崩溃通知前主动 panic。
其他进程、未指定参数或非 `1` 的取值保留原有处理流程。

主动停机原因以 `SHENG WS EXCEPTION` 开头，记录 PID、原始异常类型、两个代码值，
以及保存的用户态 PC、LR、SP、ESR 和 FAR。字段使用十六进制，文本同时进入首次 panic 面板与二维码。
缺少 ARM64 保存状态时明确输出 `state=unavailable`。

该开关在用户异常服务器处理前停止，因此命中的异常可能原本可以恢复。
它会改变启用后的运行流程，只用于定位本次 WindowServer 崩溃；不把主动停机当作原生内核崩溃。
二维码通用字段中的寄存器仍来自 panic 钩子，用户态寄存器来自 `REASON` 中的定向诊断文本。

## WindowServer 对齐取证

同一停机开关遇到 `EXC_BAD_ACCESS`、`EXC_ARM_DA_ALIGN` 时，输出紧凑的 `SHENG WS ALIGN` 记录。
其他异常保留原来的 `SHENG WS EXCEPTION` 格式。新增分支尚待实机验证。

| 字段 | 含义 |
| --- | --- |
| `p` | 当前 PID，十进制 |
| `pc`、`lr`、`sp`、`esr`、`far` | 保存的用户态异常状态，十六进制 |
| `sc` | 查询时的 `SCTLR_EL1`，十六进制；位 1 为对齐检查位 A |
| `par` | 对 FAR 执行 `AT S1E0W` 后读取的原始 `PAR_EL1` |
| `i` | 故障 PC 处的 32 位指令字，以及 `/` 后十进制 `copyin` 返回值；返回 0 才表示读取成功 |
| `slide` | 持有共享区域引用期间读取的 `sr_slide`；没有共享区域时为 `ffffffff` |

取证先使用 `copyin` 读取指令，失败时保留错误值，不直接解引用用户地址。
地址转换查询与 PAR 读取期间屏蔽异步异常，随后恢复原有 PAR 和 DAIF。
查询只检查当前翻译环境下 EL0 写权限及 Stage 1 转换结果，不读取目标像素，也不修改映射。
它不能证明没有 EL2 Stage 2 限制；返回值的位 0 为 1 时表示转换失败，不解析为物理地址。
查询成功时再按 [Arm 架构手册](https://documentation-service.arm.com/static/606f045785368c4c2b1c198c)解释地址和属性字段。

该摘要连同源码位置控制在二维码现有的 256 字节原因上限内。
指令读取和区域引用发生在主动 panic 之前，不能把该机制作为任意内核崩溃路径的通用安全读接口。

## 其他调试路径

QEMU 观察器 `scripts/observe_macos26_kernel.py` 可通过 GDB 读取保留日志、寄存器和独立 panic 区。
`scripts/decode_xnu_panic.py` 解码配套 XNU 的 version-8 panic 头，校验 CRC、UUID 和范围。
只使用同次链接的内核及 dSYM，不用原版 T8103 符号代替 SHENG 自构建符号。

内核已包含 KDP 符号，但 sheng 尚无可用的双向轮询收发后端。
ADB 和 fastboot 分别属于 Android 与 ABL，不能充当已停止的 XNU 的 KDP 通道。

旧 DarwinBoot `NEXTLOG.BIN`、`CAPxxxxx` 及 Linux RAM reader 依赖重启后 RAM 保留。
它们没有通过本轮实机捕获验收，不能与已通过的 `SHENGLOG.BIN` 周期写入混为一谈。
实现与失败记录保存在[历史调试记录](history/debugging-before-panic-qr.md)。

原始照片、录像、分区镜像和运行日志仅保存在本地 `private/`，不提交仓库或上传 CI。
