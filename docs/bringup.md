# macOS 27 / sheng 开发入口

目标是 macOS 27.0 / 26A428 / J700；硬件是 sheng / SM8550 / Adreno 740。
上游的 iPadOS 17 内核不是 macOS 27 的可替代内核。

## 获取源码

```sh
python3 scripts/sources.py fetch --group all
python3 scripts/apply_patches.py
python3 scripts/sources.py verify --group all
```

现有目录只在 HEAD 匹配时复用，不重置用户改动。主仓库只管理原创代码、补丁和锁文件。
`sources.lock.json` 固定上游提交，Git 子模块仍采用各父仓库的 gitlink。
UEFI 的深层构建依赖可用 `git -C uefi-sheng submodule update --init --recursive --depth=1 --jobs=4` 补齐。
两套 Mesa 保留独立提交，尚未应用各自补丁或配置编译。

## Apple 输入

```sh
python3 scripts/fetch_inputs.py --jobs 8
python3 scripts/fetch_inputs.py --kind kdk
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/extract_guest.py
python3 scripts/check_apple.py
```

IPSW 来自 Apple CDN，大小和哈希由 CDN 元数据固定。KDK 来自 Dortania 镜像，先校验下载哈希；
在 Mac 安装前还须通过 `pkgutil --check-signature` 验证内部 Apple 安装包签名。
手动工作流的 `apple` 目标在 macOS runner 校验签名，并展开包验证 T8140 内核 UUID；不安装到用户电脑。
获取引导组件复用 UniXNU 的范围读取和 Snapintosh 的 IM4P 解码器，结果必须匹配上游四项哈希。
完整 IPSW、KDK、解包内容和 ABI 还原结果都留在忽略目录。

## 设备探测

```sh
mkdir -p out/probes
aarch64-linux-gnu-gcc -O2 -Wall -Wextra -Werror -static probes/cpu_id.c -o out/probes/cpu-id
python3 scripts/capture_device.py --cpu-probe out/probes/cpu-id
```

只将探针放到 `/data/local/tmp`，运行后删除。不会请求 root、重启或写入分区。
EL0 的 ID 值可能由 Linux 模拟，不能据此确认 NV2 不存在或宣告监控层可运行。
采样范围由当前进程 CPU affinity 决定，不能把部分 CPU 结果扩展到整机。

UEFI 探针在已有 ShengPreflight 上扩展，补丁位于 `patches/ShengPreflight/`。
MP Services 可用时读取已启用的 AP，不擅自启动禁用核心。协议不可用时只报告启动核。
输出包括 CurrentEL、ID 寄存器、定时器频率、所有 UEFI 内存描述符和 GOP。
它只读取特性声明，不执行 NV2、PAC、页表切换或调试陷入测试，不退出 Boot Services。

```sh
CLANG_BIN=/path/to/llvm/bin/ bash scripts/build_preflight.sh
python3 scripts/gates.py private/device/preflight.log --output private/device/assessment.json
```

独立 EFI 应用不是 Android 启动镜像。部署前需要可读的原始 GPT、boot/recovery 备份，
以及已验证的恢复路径。没有这些条件不写入 UEFI 或分区。
评估程序即使接受寄存器声明，仍会拒绝缺少行为验证记录的环境。

在已开启 root ADB 的 sheng Recovery 中备份：

```sh
python3 scripts/backup_device.py --output private/backups/run-name
```

保存六个 UFS LUN 的两份 GPT，验证头部及分区数组 CRC 和副本一致性。
保存两套 boot、init_boot、vendor_boot、recovery、dtbo、vbmeta、vbmeta_system、uefi，
并将本地文件哈希与设备重新读取的哈希核对。这不包含 Android 用户数据。

## 完整 UEFI 固件

```sh
python3 scripts/build_firmware.py --llvm-bin /path/to/llvm/bin --iasl-bin /path/to/iasl/bin --fetch-firmware
```

复用上游的固定厂商包、DTS、模块导入、固件构建和 FV 检查，不执行刷写。
厂商包约 7 GiB，先验证上游固定 MD5 及完整 SHA-256，再提取所需文件。
UEFIExtract 源码版本也在锁文件中；需要 CMake 3.22+，或由 uvx 获取固定 CMake 3.31.6。
默认板级配置为 `SHENG_VENDOR_HW=0`，FV 检查的厂商模块覆盖数必须按实际配置解读，
不能把 0 个厂商模块参与检查说成全部厂商模块均已验证。
加 `--bootimg` 可以封装只含 UEFI 的 Android 容器，验证 header、gzip、FD 和追加 DTB 的往返一致性。
无 QEMU 时明确记录执行测试未运行。它不含 macOS 内核或用户态，也没有证明 ABL 会接受该镜像。

## 构建与状态

GitHub Actions 只接受手动触发。`check` 运行输入拒绝测试；`preflight` 构建 EFI；
`monitor` 在 `xcode-27` 上构建上游监控层，不含 sheng 硬件资格认证。
`kext` 检查精确 KDK 与私有 ABI 头，缺失时明确失败；`xnu` 在没有匹配源码和 ABI 前明确拒绝旧内核构建。
这些入口没有部署动作，不能用构建结果替代实机启动记录。

当前移植阶段仍是输入和硬件入口验证。尚无 sheng 的 SPTM/TXM 实机运行、macOS 启动、
Adreno 740 macOS 驱动或双系统安装结果。

## 双系统

预期总空间为 96 GiB，包含引导空间和 APFS。不要使用上游硬编码的 userdata 扇区边界。
先完成 GPT、引导/恢复和 Android 数据备份及恢复验证，再在离线环境重建 userdata。
当前不提供未经实机布局验证的分区写入脚本，不修改 XBL、ABL、TZ 或 HYP。
