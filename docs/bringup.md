# 构建与设备操作

本文说明 macOS 26.5 / 25F71 SHENG ARM64E 内核的输入准备、构建和产物获取方式。
完整内核构建使用 macOS 工具链；Linux 本地用于输入处理、重定位、封装和 QEMU 调试。
所有命令均在仓库根目录执行。

## 环境要求

| 操作 | 环境与工具 |
| --- | --- |
| 获取源码和输入 | Git、Python 3.13、uv、网络连接 |
| Actions 构建与下载 | 已登录的 GitHub CLI，以及仓库工作流和输入缓存访问权限 |
| macOS 本地构建 | 工作流使用的 Xcode/SDK、配套 KDK，以及 CMake、Ninja、unifdef |
| Recovery 解密与检查 | `config/ipsw-tool.json` 固定的 ipsw 可执行文件、7z |
| 实机临时启动与取证 | ADB、fastboot、已验证的固件容器及当前设备恢复材料 |

当前工作流使用 `xcode-27` runner，并记录实际工具链身份。
更换工具链后的构建需要单独验证，不能套用已有 runner 的结果。

## 准备源码和 Apple 输入

1. 创建 Python 环境并安装输入处理依赖：

   ```sh
   uv venv --python 3.13 .venv
   uv pip install --python .venv/bin/python -r requirements.txt
   ```

2. 获取锁定版本的源码，并应用本项目补丁：

   ```sh
   python3 scripts/sources.py fetch --group all
   python3 scripts/sources.py fetch --lock config/macos26-sources.json --group macos26
   python3 scripts/apply_patches.py
   ```

3. 下载配套 IPSW。需要在本地编译时，同时下载 KDK：

   ```sh
   python3 scripts/fetch_inputs.py --config config/macos26.json --jobs 8
   python3 scripts/fetch_inputs.py --config config/macos26.json --kind kdk --jobs 8
   ```

   获取器检查固定大小和 SHA-256。KDK 的包签名及内核 UUID 另由 macOS 上的 `verify_kdk.sh` 核对。
   Apple 输入保存在忽略目录中，不提交仓库。

恢复卷准备还要求已有匹配的提取清单 `private/apple/macos26/inventory.json`。
该清单由 `scripts/inspect_macos26.py` 生成，包含板型、组件文件名和哈希。
具备固定 ipsw 工具后执行：

```sh
.venv/bin/python scripts/inspect_macos26.py
python3 scripts/prepare_macos26_recovery.py --ipsw-tool /path/to/pinned/ipsw
```

将 `/path/to/pinned/ipsw` 替换为实际工具路径。脚本拒绝工具哈希或输入清单不匹配的文件，
并在 `private/apple/macos26/recovery-check/verification.json` 记录恢复系统版本和用户态架构检查结果。

## 使用 GitHub Actions 构建

1. 触发 ARM64E 内核和配套实验驱动构建：

   ```sh
   gh workflow run bringup.yml --repo CrossDarwin/macOS-ForSheng --ref main \
     -f target=macos26-kernel -f native_arch=arm64e \
     -f native_ufs=true -f native_gop=true -f native_input=true
   ```

2. 查找本次运行，并核对提交和结果：

   ```sh
   gh run list --repo CrossDarwin/macOS-ForSheng --workflow bringup.yml --limit 5
   gh run view RUN_ID --repo CrossDarwin/macOS-ForSheng
   ```

3. 构建成功后，将内核产物下载到一个新的目录：

   ```sh
   gh run download RUN_ID --repo CrossDarwin/macOS-ForSheng \
     --name macos26-sheng-kernel --dir private/ci/CAPTURE
   ```

`RUN_ID` 必须替换为核对过的运行编号，`CAPTURE` 必须替换为未使用的目录名。
产物包含内核、`build.json`、链接 map、匹配 dSYM 及所选驱动目录。
失败构建的日志位于 `macos26-sheng-diagnostics` 产物中，应从第一个实际错误定位问题。

`native_input` 构建 QEMU VirtIO HID 驱动，不实现 sheng 触控。
UFS、GOP 和输入驱动由运行时参数及设备描述启用，构建工作流不部署设备。

## 在 macOS 本地构建

配套 KDK 已解包且工具链与工作流一致时，执行：

```sh
python3 scripts/build_macos26_xnu.py --arch arm64e --link-kernel \
  --build-ufs-driver --build-gop-display --build-recovery-input \
  --kdk-root /path/to/paired-kdk -j 4
```

`--kdk-root` 指向实际 KDK 内容目录。ARM64E 产物输出到 `out/macos26-xnu-arm64e/`。
构建器记录源码、补丁、工具链和文件哈希，并保留未剥离内核、dSYM 和链接 map。
已有对象目录用于增量构建，不需要删除 `out/`。

## 生成启动候选

`scripts/emit_macos26_security.py` 将配套组件和驱动重定位到本次内核，保留 PAC 元数据。
内核、组件身份、存储驱动和符号文件必须配套，加载机制见[安全组件说明](macos26-security.md)。
`scripts/package_macos26_ufs.py` 根据引导、根卷、默认关闭路径及所选功能的观察记录封装硬件候选。
两者的完整参数分别由 `--help` 提供。

仅替换 RAM 包内内核的诊断候选可以复用已有固件、设备树和磁盘。
这种候选须记录复用来源及尚未重新验证的项目；运行结果统一写入[移植状态](status.md)。

## 实机布局与临时启动

以下布局仅描述当前已配置的实验设备，不是其他设备的分区操作指南。
该设备已划出 64 GiB `macosroot`，其余空间重建 Android userdata；原 userdata 已清除。
恢复旧 GPT 无法恢复原数据。

| 分区 | 用途 |
| --- | --- |
| `macosroot` | LUN0 上的根盘窗口，承载配套 BaseSystem |
| `macoslog` | LUN4 上的 64 MiB FAT16 分区，保存预分配日志文件 |
| Android userdata | 重建后的 Android 数据分区 |

当前设备使用临时 `fastboot boot` 加载候选。执行前核对候选身份、活动槽和可启动状态。
`Booting OKAY` 表示 ABL 接受启动交接；内核和服务是否执行，由屏幕及日志确认。
该流程不要求刷写 boot、Recovery 或厂商固件分区。

设备备份保存在本地 `private/backups/`，运行记录保存在 `private/device/` 或 `private/experiments/`。
日志导出见[日志与崩溃诊断](debugging.md)，旧参考内核和固件实验见[历史构建记录](history/bringup-20261026.md)。
