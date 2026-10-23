# 实施状态 - 2026-10-23

目标保持 macOS 27.0 / 26A428。用户已允许必要的旧内核实验；尚未构建或启动旧 XNU。

| 项目 | 状态 |
| --- | --- |
| UniXNU、Snapintosh、q1n1、依赖与两套 Mesa | 已固定提交并获取，补丁保存在本项目 |
| 完整 26A428 IPSW | 下载完成，SHA-256 与 Apple CDN 元数据一致 |
| J700 kernelcache / ADT / SPTM / TXM | 四项哈希与上游客体配置一致 |
| 对应 KDK | 下载哈希、Apple 包签名、T8140 内核及配对 DWARF UUID 验证通过 |
| ShengPreflight | 实机运行完成；照片已取得启动核寄存器、内存统计和 GOP 摘要；MP Services 不可用 |
| 上游 EL2 监控层 | 本地及 xcode-27 Actions 编译通过，仍为 A16 构建基线 |
| 完整 sheng UEFI | 本地构建及 FV 检查通过；fastboot 临时启动成功，菜单和探针输出已由照片及视频确认 |
| 设备备份 | 六个 LUN 主备 GPT、16 个引导分区已读取并校验，userdata 未备份 |
| macOS 实机启动 / 双系统 | 未实现；未刷写分区镜像或调整分区；已恢复 Android，boot_completed=1，活动槽 _a |

## 已定位的引导问题

此前黑屏会自动复位并进入 fastboot。root Recovery 读取的 logfs 保留了 ABL 的失败路径：
`Boot image header OS version == 0`、`LoadImageAndAuthVB2() ... Invalid Parameter`，
随后 ABL 将活动槽标记不可启动并切换槽位。该日志属于镜像认证阶段，不是 XNU 崩溃。

以未压缩 UEFI 容器为对照，只将 v4 header 的 OS 字段从 0 改为当前 boot_a 备份的
`0x220001a8`，`fastboot boot` 返回 `Booting OKAY`，屏幕进入 UEFI 菜单。
成功容器 SHA-256 为 `c20548f25ce139c9bef4f3974fb461fe62736d0969eac6920f605172853daa15`。
选择菜单的 UniXNU 后实际运行 ShengPreflight。随后构建的摘要候选
`3aec7db6c8775e3689ca78f8d0d505482a7cc4024d0563950be5339e2f13004c`
也已接受并运行完成，末页等待按键，照片已保存。两项 BootShim QEMU 用例和 21 项离线测试通过。

启动核报告 `MIDR=0x411fd461`、`EL=1`、`MMFR2=0x1221011110101011`、
定时器 19200000 Hz。NV 字段 `[27:24]` 为 0，当前环境未宣告 NV2。
这不是在不受虚拟化影响的 EL2 读取，不能据此断言所有物理核心均缺少 NV2。
MP Services 返回 Not Found，`total=1 enabled=1` 是启动核回退值，不是整机核心数量。
本次只确认启动核，未完成各类核心与行为探测。

UEFI 内存描述符统计为 69 项，conventional-pages=1797591，reserved-pages=256561；
摘要照片不包含全部描述符。GOP 为 3048×2032，stride=3048、format=1、
base=0xb8000000、size=0x17a0600。该地址属于显示缓冲区，不作为监控层可用内存。

`scripts/capture_boot_logs.py` 可读取并校验 logfs、xbl_sc_logs 和 rawdump 的前 1 MiB，
提取五个 UefiLog 文件。rawdump 中发现旧 Android 启动信息，不能归因于本次实验。
这些持久日志属于原有固件，不等于实验 UEFI 已具备持久日志输出。

## 当前阻塞

Recovery 的实际内核日志确认全部 CPU 从 EL1 启动，KVM 报告 HYP mode not available。
这证明当前 Android/Recovery 交接没有提供可直接使用的 EL2；不证明所有其他固件入口都不可能。
Snapintosh 的现有监控层要求 EL2，因此不能直接放进这条启动链。
EL0 采集到的 ID 寄存器经过 Linux 过滤，NV2 的物理实现与 UEFI 行为测试仍未确认。

原版 J700 内核标识为 Darwin 27.0.0 / XNU 13432.1.9 / T8140。
本次查询 Apple 官方 XNU 仓库，没有找到 xnu-13432 系列标签，所检查 main 仍为 xnu-12377.1.9。
现有 XNU 10063.141.1 是 iPadOS 17 基线，不能作为 macOS 27 的重编译替代。

下一阶段需要验证可用的 EL2 入口，或证明 macOS 27 内核在 EL1 的独立适配方案。
旧 XNU 可用于独立验证 EL1 下的硬件交接；尚无与 macOS 27 用户态兼容的证据。
在解决启动路线、完成用户数据备份与恢复验证之前，不实施 96 GiB 分区变更。
