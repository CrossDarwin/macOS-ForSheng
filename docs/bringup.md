# 构建与设备操作

当前目标是 macOS 26.5 / 25F71、XNU 12377.121.6 ARM64E 和 sheng / SM8550。
以下命令在仓库根目录执行。构建不自动部署，封装不代表实机运行通过。
已有缓存和观察结果只在相关输入变化时重新验证，不执行无关全量构建。

## 准备源码与输入

需要 Git、Python、uv 和具备本仓库访问权限的 GitHub CLI。
固定提交来自锁文件；Apple 输入留在忽略目录，不上传仓库或第三方服务。

```sh
python3 scripts/sources.py fetch --group all
python3 scripts/sources.py fetch --lock config/macos26-sources.json --group macos26
python3 scripts/apply_patches.py
python3 scripts/fetch_inputs.py --config config/macos26.json --jobs 8
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

获取器核对固定版本、大小和 SHA-256。恢复卷还需通过 `prepare_macos26_recovery.py` 使用固定 ipsw 工具解密和检查。
macOS 编译使用配套 KDK，其签名、内核 UUID 与输入约束见 `config/macos26.json`。
不能用版本相近的 KDK 或其他板型符号代替匹配输入。

## 当前构建入口

GitHub Actions 的 `bringup.yml` 只接受手动触发。原生内核及配套实验驱动使用：

```sh
gh workflow run bringup.yml --repo CrossDarwin/macOS-ForSheng --ref main \
  -f target=macos26-kernel -f native_arch=arm64e \
  -f native_ufs=true -f native_gop=true -f native_input=true
```

`native_input` 构建 QEMU VirtIO HID 驱动，不表示 sheng 触控可用。
UFS、GOP 和输入路径默认关闭，运行时由对应设备描述和参数启用。

具备配套 macOS 工具链和 KDK 的主机可执行同一构建脚本：

```sh
python3 scripts/build_macos26_xnu.py --arch arm64e --link-kernel \
  --build-ufs-driver --build-gop-display --build-recovery-input \
  --kdk-root /path/to/paired-kdk -j 4
```

`/path/to/paired-kdk` 是占位路径，必须替换。脚本记录工具链、源码、补丁、UUID、dSYM 和链接 map。
当前完整内核编译主要使用 Actions；Linux 本地用于准备输入、重定位、封装和 QEMU 运行。
`sheng-xnu` 与 `reference-xnu` 属于旧 XNU 10063.141.1 硬件参考，不用于启动当前用户空间。

## 组件生成与封装

`scripts/emit_macos26_security.py` 将配套组件及驱动连接到本次内核，保留 PAC 元数据。
模块集合、目标目录和存储驱动必须来自同次构建，不能复用另一个内核的 UUID 或符号记录。
生成后的初始化和运行结果见[安全组件说明](macos26-security.md)。

常规硬件封装入口为 `scripts/package_macos26_ufs.py`。
它要求内核引导、根卷、默认关闭路径、磁盘部署及所启用功能的匹配观察记录。
参数以脚本 `--help` 为准；缺失记录时不生成虚构的通过结果。
本轮诊断候选按用户要求复用已有固件、设备树和磁盘，只替换 RAM 包中的内核及诊断参数。
复用范围和未重复的验收项必须单独记录，不能把旧内核证据改成新内核证据。

## 设备布局与临时启动

当前实验设备已按授权划出 64 GiB `macosroot`，剩余空间重建 Android userdata。
旧 userdata 已清除，恢复旧 GPT 不会恢复原数据。这个重分区操作不是日常启动步骤。

| 分区 | 当前用途 |
| --- | --- |
| `macosroot` | LUN0 的独立根盘窗口，承载配套 BaseSystem |
| `macoslog` | LUN4 的 64 MiB FAT16 日志分区，内核更新预分配文件 |
| Android userdata | 重建后的 Android 数据，独立于上述实验分区 |

主备 GPT、引导分区和当前恢复材料保存在本地 `private/backups/`。
UFS 根卷读取、BaseSystem 挂载和日志文件读回已有实机结果，详见[当前状态](status.md)。
实验继续使用临时 `fastboot boot`。启动前核对当前槽和可启动状态；返回 `Booting OKAY` 只说明 ABL 接受交接，
是否执行内核和服务需要屏幕或日志确认。不得因此自动刷写 boot、Recovery 或厂商固件分区。

## 日志与验证

运行时记录 UUID、实际加载地址和最后画面，原始数据仅保留在本地。
从 Android Recovery 读回日志的方法见[日志与崩溃诊断](debugging.md)。

验证按修改范围选择：地址修正检查实际指令，panic 二维码检查 ARM64 画屏和解码，
显示与用户态变化再观察对应服务和帧提交。构建通过、断点命中和驱动注册分别不能代替指令执行、界面显示和实机验收。
旧固件、探针和分区操作记录见[历史构建说明](history/bringup-20261026.md)。
