# 实施状态 - 2026-10-23

系统目标已改为配对的 macOS 26.5 / 25F71。旧 XNU 独立验证 EL1 硬件交接，不能作为 macOS 26/27 用户空间的替代内核。

| 项目 | 状态 |
| --- | --- |
| UniXNU、Snapintosh、q1n1、依赖与两套 Mesa | 已固定提交并获取，补丁保存在本项目 |
| 25F71 IPSW 与公开源码 | 完整 ARM IPSW 已下载且 SHA-256 通过；三套内核版本均匹配 XNU 12377.121.6，九项公开源码已固定并核对 |
| 25F71 恢复卷 | AEA 解密完成；SystemVersion=26.5/25F71，launchd 与 dyld 均为 ARM64e；尚未启动 |
| 完整 26A428 IPSW | 旧目标参考；下载及固定 SHA-256 校验完成 |
| J700 kernelcache / ADT / SPTM / TXM | 四项哈希与上游客体配置一致 |
| 26A428 KDK | 下载哈希、Apple 包签名、T8140 内核及配对 DWARF UUID 验证通过 |
| ShengPreflight | 实机运行完成；照片已取得启动核寄存器、内存统计和 GOP 摘要；MP Services 不可用 |
| 上游 EL2 监控层 | 本地及 xcode-27 Actions 编译通过，仍为 A16 构建基线 |
| 完整 sheng UEFI | 本地构建及 FV 检查通过；fastboot 临时启动成功，菜单和探针输出已由照片及视频确认 |
| 设备备份 | 六个 LUN 主备 GPT、16 个引导分区已读取并校验，userdata 未备份 |
| 完整上游 sheng 配置 | 35 项与上游字节一致，19 个归档步骤全部保留；原版输入、实际 QEMU ABI 记录和 VerifiedRoot 策略已重建，完整归档构建待验 |
| EL1 参考内核 | XNU 10063.141.1 已在 Actions 39905217735 构建通过，使用 gzip 和备份中的厂商 DTB 后已进入 XNU；MMU 后 3 秒复位探针实机通过 |
| 加载器合成交接 | QEMU 实测 boot_args、ramdisk、trustcache、清零与关闭 MMU 交接通过；不是 XNU 启动 |
| macOS 实机启动 / 双系统 | 未实现；未刷写分区镜像或调整分区；当前进行临时启动实验，槽 a |

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

旧目标 J700 的 macOS 27 内核标识为 Darwin 27.0.0 / XNU 13432.1.9 / T8140。
Apple 当前公开的 macOS 26.5 发布清单固定 XNU 12377.121.6；尚未取得对应 13432 的公开源码。
因此当前真实系统试验统一采用 25F71 的内核、恢复卷和用户空间，不混用 26 内核与 27 用户空间。

原生路线优先研究 M1/T8103。它不在该版 macOS 的 SPTM 启用列表里，但仍有 Apple 平台依赖。
VMAPPLE 也不能直接复用，其 PAC 密钥路径通过 HVC 请求宿主服务，当前 EL1 没有该服务。
Neo/T8140 与 Snapintosh 保留为对照。详见 [路线依据](routes.md)。

独立 EL1 实验采用 UniXNU 的 XNU 10063.141.1，启动核 ADT 根据实测 MIDR 描述为 Cortex-A510。
参考内核在 xcode-27 编译完成，初始 4 KiB 页表审计通过。
首轮 v0 未压缩容器因 DTB offset is NULL 被拒绝；gzip 后进入 DTBO 阶段，但主线 DTB 不兼容厂商叠加。
改用已备份 vendor_boot 中的厂商 DTB 后，实机照片确认 XNU 入口蓝条与启用 MMU 前紫条。
后续镜像在 MMU 后探针处等待 3 秒并复位，用户观察与设计一致；复位后 Android boot_completed=1、槽 _a。
C 初始化中的 arm_vm_init、serial_init、第一轮 kernel_startup_initialize_upto 和第一条 kprintf 返回后复位探针均已触发。
PE_create_console 返回后探针未触发。该函数的真实产物仍映射并读取 BCM2837 的固定 panic 地址 0x3c0fc000。
精简配置漏掉上游 XNU_DT_PANIC_REGION，已补齐并重编译；这处访问是待验证的阻断原因。
用户要求以完整上游配置为准后，新增完整 sheng 构建入口，不再将精简参考配置作为完整设备基线。

## 上游缺失产物重建

完整构建 39908905205 已完成前九个归档步骤，第十步缺少 `storage-abi/interface-audit.json`。
未禁用相关配置，也未以占位归档替代。重建记录固定于 `config/sheng-reconstructed-inputs.json`。

临时 ABI 实验使用与完整配置一致的 `prelinked` crypto 初始化方式，避免与原版 corecrypto 重复注册 PRNG。
Actions 39909466130 产物源码内核 SHA-256 为
`de632dd122173ed937aaf666ae15b906be8db5da8ddfb37580d3597ef58b51a5`。
加上固定原版组件后的候选 SHA-256 为
`c4053ab8e48659b6a55f2bf7d685b2a8258cdf8fbcdc4640efae2a29b3130c30`。
该候选仅用于 ABI 实验，未部署设备，不能作为完整配置构建结果。

实际 QEMU TCG 已通过 MMU、控制台、原版 corecrypto、Image4、AMFI 初始化并停在 `bsd_init`。
前两次 panic 分别由合成 ADT 缺少 `crypto-hash-method` 和 `amfi-only-platform-code` 引起，
补齐上游已有参数后通过，未修改原版组件指令或跳过检查。
只读调试记录取得 IOBlockStorageDevice/IOService 实际大小 `0x90`/`0x88`，页表为原生 4 KiB。
另一次实际构造函数返回记录取得 IOMobileFramebufferLegacy 元类 `0xfffffff006b35940`、
父类 `0xfffffff006b31400` 和大小 `0x18a0`。这些是 QEMU ABI 结果，不是 sheng 显示驱动验收。
原版 PMGR 指令和 Legacy 358 槽静态审计已通过；存储注解对象仍需 macOS 编译验证。

OS 完整虚拟介质由 UDIF 六段原始内容还原，6077580800 字节，SHA-256 与上游固定值
`e5634d04a8ac35f024845f583394e0a35deb26a04cb0c00286a8674e25a9a4f2` 一致。
SystemOS 原始 APFS 为 3303014400 字节，SHA-256 为
`b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f`。
两卷 UUID 均从实际 APFS 读取，再以同一私有测试所有者密钥签名。
实际 C 验证器检查了 OS 1483785 块、SystemOS 806400 块及 RSA3072 签名；七组负向检查通过。
策略归档仅包含公开信任锚、签名、哈希表、必要原始样本与验证记录，不包含私钥。
重建脚本为 `scripts/rebuild_sheng_policies.py`；最后一个 OS 块的实际长度仍为 1536 字节。

私有输入缓存包含已验证的原版内核、候选及实际观察记录，并固定整个归档和每个文件的哈希。
为兼容上游构建器，候选按其期望文件名暂存；这些名称不表示已完成 rootauth 或设备资格验证。
完整构建在真实编译记录生成后执行存储 ABI 审计及 VerifiedRoot/VirtIO 归档编译，再运行原有 19 步。
输入不匹配、运行记录超时、ABI 不一致或归档缺失均使构建失败。

尚无 launchd 或 macOS 用户空间运行结果。
该阶段不带系统用户空间，也不链接 UFS 写入后端。QEMU 的合成交接已通过，但不能替代真机结果。
在解决系统启动路线、完成用户数据备份与恢复验证之前，不实施 96 GiB 分区变更。
