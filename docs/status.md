# 实施状态 - 2026-10-23

系统目标已改为配对的 macOS 26.5 / 25F71。旧 XNU 独立验证 EL1 硬件交接，不能作为 macOS 26/27 用户空间的替代内核。

| 项目 | 状态 |
| --- | --- |
| UniXNU、Snapintosh、q1n1、依赖与两套 Mesa | 已固定提交并获取，补丁保存在本项目 |
| 25F71 IPSW 与公开源码 | 完整 ARM IPSW 已下载且 SHA-256 通过；三套内核版本均匹配 XNU 12377.121.6，九项公开源码已固定并核对 |
| 25F71 KDK | Actions 39925158581 通过 Apple 包签名及 M1/T8103、Neo/T8140 内核与配对 DWARF UUID 检查 |
| 25F71 恢复卷 | AEA 解密完成；SystemVersion=26.5/25F71，launchd 与 dyld 均为 ARM64e；尚未启动 |
| 完整 26A428 IPSW | 旧目标参考；下载及固定 SHA-256 校验完成 |
| J700 kernelcache / ADT / SPTM / TXM | 四项哈希与上游客体配置一致 |
| 26A428 KDK | 下载哈希、Apple 包签名、T8140 内核及配对 DWARF UUID 验证通过 |
| ShengPreflight | 实机运行完成；照片已取得启动核寄存器、内存统计和 GOP 摘要；MP Services 不可用 |
| 上游 EL2 监控层 | 本地及 xcode-27 Actions 编译通过，仍为 A16 构建基线 |
| 完整 sheng UEFI | 本地构建及 FV 检查通过；fastboot 临时启动成功，菜单和探针输出已由照片及视频确认 |
| 设备备份 | 六个 LUN 主备 GPT、16 个引导分区已读取并校验，userdata 未备份 |
| 完整上游 sheng 配置 | 35 项与上游字节一致，19 步及两个外部归档、预链接全部通过，Actions 39919525158 成功 |
| 完整内核实机 | 控制台、BSD 入口、BSD 缓冲区、IOKitBSDInit 前与 IOFindBSDRoot 前检查点均实机通过；Android 恢复到槽 a |
| 完整内核 QEMU | 完整配置产物经实际 UEFI/DarwinBoot 执行到 bsd_init，4 KiB 页表；未启动用户空间 |
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
此前精简配置的 PE_create_console 返回后探针未触发，其真实产物仍映射并读取 BCM2837 的固定 panic 地址 0x3c0fc000。
精简配置漏掉上游 XNU_DT_PANIC_REGION，已补齐并重编译；完整上游配置的控制台返回检查点现已在实机通过。
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
原版 PMGR 指令和 Legacy 358 槽静态审计已通过。Actions 39912573333 的实际 macOS 编译进一步通过存储审计：
190 个方法槽、176 个内核绑定、14 个纯虚槽和实际元类大小均一致；注解对象未链接或执行。
该次构建停在 VerifiedRoot 编译记录包含的不存在 libsa include 目录，已过滤失效目录；
完整配置与原版指令保持不变。Actions 39917142035 已完成两个外部归档编译及原有前 13 个步骤，
随后补齐了 BootProgress 使用的固定 UEFI 字体路径。Actions 39918233188 已通过前 18 个步骤，
最后一个 Legacy 步骤的 HID 子构建仍在寻找旧的未提供候选。现已显式传入同一原版组件载体，
原版 IOHIDFamily 哈希、207 个槽、构造/析构导入和调用约束的静态检查通过。
Actions 39919525158 进一步完成 HID 编译、最后一个 Legacy 归档及完整内核链接、审计和原版组件预链接。
固定 Novatek 触摸固件已取回并核对 SHA-256，245760 字节；不再接受空触摸固件继续完整构建。

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

`scripts/observe_sheng_abi.py --firmware <QEMU AArch64 UEFI FD>` 可从固定源码内核和原版输入重新生成候选，
再通过实际 UEFI/DarwinBoot 重放存储、Legacy 两项只读观察。独立重放已通过，
`out/sheng-abi-replay/verification.json` 保留各次 ADT、配置和原始调试记录的哈希。

NativeAdreno 所需三份固件已按上游字节数、Git blob 和 SHA-256 固定值获取。
固定 DTS 的 39 个源文件闭包已编译；GMU 寄存器、RSC/PDC 顺序、OPP 和 BCM 参数头由现有上游脚本生成。
修正了包内资源审计脚本沿符号链接定位到源码仓库而非组装树的问题，并使用实际的 `scripts/data` 清单。
这些是构建输入和源码分析结果，未观测真实 GMU 执行，也未验证 Adreno 加速。

完整配置产物已下载，GitHub ZIP 的 SHA-256 为
`cdaf43b6d6663636545508cac93b31189f51f1422c82461bedc5c889002ad0b0`，与 API 提供的摘要一致。
预链接内核为 126423040 字节，SHA-256 为
`272bbde4e72dc7ad6d2a5066c1ee622e367bb32f525bd92e9ae8e2dbd270acac`。
源码内核审计摘要为 `a8fa6115fabc42e1a8b1b28ce3acc034eee5382b46113d60a20a44ea54ed8d63`。
本地产物再次核对完整配置、19 步归档、外部归档完成标记及最终内核哈希。

该完整内核在 QEMU TCG/Cortex-A710、实际 UEFI/DarwinBoot 中停在 `bsd_init` 的
`0xfffffff00bd10008`，不是超时中断。已观察到虚拟内存、控制台、machine_startup 和 C++ 初始化，
实际 TCR 为原生 4 KiB 页表。记录位于 `out/sheng-full-qemu/verification.json`。

新的实机探针保留完整配置及全部已链接驱动，只在载荷副本插入控制台返回后的 3 秒复位检查点。
其入口在 IOKit/存储驱动初始化之前，尚不尝试挂载任何系统卷。
封装器拒绝将临时 ABI 内核冒充完整 sheng 产物，且对预链接内核再次核对源审计的实际初始 TCR。
FAT 与 Android 容器往返校验通过，镜像为 163241984 字节，SHA-256 为
`f7bd670c709b882ee3961f30dc841990a56326d3bc8b665bab538a16a6e350be`。
部署前 ADB 实测 Android boot_completed=1、槽 _a；随后 fastboot 核对 sheng、解锁、活动槽及下载容量。
`fastboot boot` 返回 Sending OKAY、Booting OKAY；设备随后重新出现 ADB。
08:06 UTC 实测 Android boot_completed=1、槽 _a，bootreason=bootloader。
用户确认已选择完整 sheng 内核，彩色条出现后约 3 秒自动复位；控制台返回检查点实机通过。
未执行 flash 或 repartition。27 项离线测试通过。

尚无 launchd 或 macOS 用户空间运行结果。
该阶段不带系统用户空间；完整配置包含 UFS 驱动，控制台检查点在其初始化之前。QEMU 的合成交接已通过，但不能替代真机结果。
在解决系统启动路线、完成用户数据备份与恢复验证之前，不实施 96 GiB 分区变更。

下一轮检查点位于 `kernel_bootstrap_thread` 中调用 `bsd_init` 之前，调用地址 `0xfffffff00c0544b4`。
该位置在 IOKit、中断和内核 lockdown 初始化之后，完整驱动配置保持不变；不进入 BSD 或挂载系统卷。
载荷副本将这一条已核对目标的直接调用替换为延迟 PSCI SYSTEM_RESET，不执行被替换的调用。
修正上游诊断脚本原有 `--reset-before` 忽略延迟的问题，其前置复位与后置复位现在使用同一定时路径。
QEMU 实测已执行到复位 SMC：PC `0xfffffff00ba50650`、x0 `0x84000009`，不是超时停止。
QEMU 频率 62.5 MHz 与设备 19.2 MHz 不同；该检查验证控制流，设备延迟仍按实测 19.2 MHz 计算为 3 秒。
新容器 SHA-256 为 `a3308e6264e37e3e24500790000b0df17ec6bf38a084c25b2acac00f79cd71ff`，
载荷内核 SHA-256 为 `bef8d1198787f726760241cad509596c41d509bc6686f9b61f9f41f4e6378a2a`。
27 项离线检查与 FAT/容器往返校验通过。实机结果单独记录，不以 QEMU 代替。

BSD 入口前镜像临时启动返回 `Booting OKAY`。用户确认彩色条后约 3 秒自动复位，实机检查点通过。
复位后重新读取 Android 状态与活动槽，记录在 `private/device/full-sheng-pre-bsd-01-run.json`。
下一轮停在 `bsd_init` 调用 `IOKitInitializeTime` 之前，验证进程 0、凭据、BSD 子映射与缓冲区初始化。
该位置在 `vfsinit` 和根文件系统挂载之前，不执行被替换的时钟初始化调用。

BSD 缓冲区检查点的 QEMU 实际执行通过，调用地址 `0xfffffff00bd104e0`。
容器 SHA-256 为 `3ec866505b1a5b26d50e63c21503a54223ddd33f8ae1e4cbf907961567526998`；
载荷内核为 `8a0d08e227a192be2adf102c51ba650c94b940b4e5c27bfd92644974988787aa`。用户确认彩色条后约 3 秒自动复位，BSD 早期初始化实机通过。

设备自动配置前的下一检查点选在实际产物 `bsd_init` 内对 `IOKitBSDInit` 的直接调用之前，地址 `0xfffffff00bd107f4`。
`bsd_autoconf` 已被编译器内联，没有可供原有探针替换的独立调用；封装器对此明确拒绝，未发送失败候选。
QEMU 实测新的调用前复位路径通过，BSD 已执行 VFS 框架、事件、POSIX 线程及网络初始化，但尚未调用 `IOKitBSDInit`。
容器 SHA-256 为 `6ad7b2c1365c17a31ccc4cac9470a20c9357c3c1c74b36c1003f13cda950c362`，载荷内核为 `03f57caae56ae822edc18ba11f2260592422bfac7bea730f7acd0e6d9f95bd74`。
用户确认彩色条后约 3 秒自动复位，设备自动配置前检查点实机通过。

继续推进到 `bsd_init` 调用 `IOFindBSDRoot` 之前，尚不执行根设备查找或挂载。
固定上游 `NativeUfs::start` 在 `native-ufs-probe` 与 `native-ufs-root` 均为零时直接返回 false，早于控制器映射和任何硬件命令。
测试配置只传入 `-v debug=0x100 keepsyms=1 cpus=1`，没有这两项启用参数，不沿用上游 board.toml 的 UFS root 参数。
此为启动参数隔离，完整 35 项编译配置和已链接驱动保持不变。

根设备查找前镜像 SHA-256 为 `d2fd15f42a1ed132e3e04107d39c58a5506a4979c38ca070a9f2a63f077c87a0`，
载荷内核为 `9ef56570f6e8d0f0eab1ec15c6764df4b06e2b829ba87c4236d04866ca7e63d8`。
QEMU 与实机均通过该检查点；用户确认彩色条后约 3 秒自动复位。Android 已恢复完成，槽 _a。
硬件参考内核至此已执行到根设备选择前，不再增加旧用户空间启动实验。macOS 26.5 的源码迁移与 ABI 验证单独推进。

macOS 26.5 KDK 验证新增独立的 `apple26` 手动 Actions 目标，仍在 `xcode-27` 上执行。
下载后核对固定字节数和 SHA-256，再以 macOS `pkgutil --check-signature` 验证 Apple 签名。
从同一包中分别检查 M1/T8103、Neo/T8140 的内核与配对 DWARF，UUID 必须与 25F71 IPSW 相符。
Actions 39925158581 成功，原始签名日志和配对 UUID 报告已下载并再次核对。28 项本地检查通过。

固定 macOS 26 源码的独立补丁上下文检查覆盖上游 55 份补丁，35 份可直接通过 `git apply --check`，20 份需要逐项处理。
这是每份补丁相对原始源码的检查，不是完整补丁栈应用、编译或 ABI 验证。
该版已无 BCM2837 平台头和 MASTER 配置；`source-machine-layer`、架构定时器入口、SMP、4K 用户空间与启动进度补丁不能原样套用。
原有非 Apple pmap 字段重命名修复对应的字段在新版本已有不同布局，不重复移植旧修复。
缓存维护别名、monitor 启用条件、SART 及分散到新文件的 pmap 路径需要按 12377.121.6 的实际实现迁移。
原始报告位于 `out/macos26-transfer/upstream-patch-contexts.json`，未改动固定的 macOS 26 源码树。

25F71 KDK 实际验证结果：Apple 包签名通过，M1/T8103 UUID `DA4C776A-B10A-38B6-997B-BD66671C5D52`、
Neo/T8140 UUID `6F5E696D-EDA7-3AA0-91DC-24B13CF58148` 均与各自 IPSW 内核及 KDK DWARF 一致。
这建立了配对调试输入，不等于私有 IOKit ABI 或 sheng 硬件适配已通过。
[验证工作流](https://github.com/Jelly10086/macOS-ForSheng/actions/runs/39925158581)。

## macOS 26 原生平台源码构建

新增 `scripts/build_macos26_xnu.py` 和独立 `SHENG` 目标，固定 XNU 12377.121.6 / Darwin 25.5.0。
固定源码树保持干净，补丁只应用到 `out/macos26-xnu/source`。已有完整 sheng 配置和 19 项归档清单保持原样。
本轮编译采用 macOS 26 的 MacOSX 配置，启用实际 ARM 汇编和 pmap 源文件，使用原生 EL1、4 KiB 页表及架构定时器路径。
不定义 VMAPPLE、Apple CPU、SME/SME2 或虚拟 PAC 服务。Apple 专属性能计数器不在此物理平台启用。
缓存维护、monitor 条件和 SART 路径按 12377.121.6 重新迁移，设备树 panic 缓冲区路径仍保留。

现阶段构建普通内核翻译单元的归档，再以真实 IOPlatformExpert 编译记录重编 ArmDTPlatform/ArmCpu。
构建时保留 `-mkernel` 与 `-Werror`，不链接 Apple SoC 机器支持库，不复用旧 iPadOS 二进制归档，不输出设备启动镜像。
源码归档、可链接内核、驱动 ABI、QEMU 和实机启动分别记录，不能互相替代。

本地真实编译器已生成 macOS 26.5 ARM64 平台头检查对象，确认无 Apple/VM/SME 平台定义；
错误部署版本拒绝检查和未记录源码改动保护通过，28 项现有测试通过。
`boot_args` 在两份固定源码中的结构声明一致，尚待新版内核编译记录验证实际布局。

Actions 39927508455 已通过匹配 KDK 签名、UUID、AvailabilityVersions 构建和新版内核头导出。
第一次源码编译因公开 SDK/KDK 不存在的私有 include 目录在 `-Werror` 下中止。
已迁移独立 kernel SDK 搜索路径，暂存固定 macOS 26 libplatform/libdispatch 头，并仅保留实际存在的目录。
缺失的实际头仍在 include 位置报错，不生成占位头，不关闭缺失目录警告。
Actions 39928465964 已消除不存在的 include 目录错误。下一处失败为系统保留名称告警和缺少 CoreEntitlements/V2/API.h。
原始 25F71 KDK 的 KDK_SDK.pkg/Payload 实际包含该头及 CodeSignature/TrustCache/TXM 头，先前构建漏用了 SDK 子包。
现已将其头文件纳入签名验证后的哈希清单，并在源码构建中逐文件核对、暂存；未引入其中的 SPTM/TXM 二进制库。
SHENG 目标仅关闭系统 ABI 保留名称的诊断，保留 -Werror 和其余检查。尚无 macOS 26 内核编译或启动通过结果。

Actions 39930215732 已通过 SDK 头哈希校验，之前的缺失头、缓存步长和保留名称错误消失。
真实源码编译已进入 BSD、IOKit 和 security，停在 VFS 调试计数及 Xcode 27 IIG 生成的 OSAction 接收器未使用变量告警。
仅为 VFS 计数添加 unused 标注，并为该生成对象设置单项诊断例外，其他对象仍启用该告警和 -Werror。
后续使用 make -k 汇总各模块实际错误，失败状态仍使工作流失败。

Android EL0 独立实机探测：CPU 0–5 的 MIDR 分别覆盖 0x411fd461、0x411fd4d0、0x412fd470，
CTR_EL0 均为 0x49444c004，公开给该程序的 I/D 缓存维护步长均为 64 字节。
各核 PACIA 确实改变指针，AUTIA 恢复原值，基本指令往返通过。
CPU 6–7 的 sched_setaffinity 返回 -EINVAL，未验证；CTR/MIDR 读取可能受 Linux 模拟或归一化处理。
原始二进制结果、探针源码/可执行文件及 SHA-256 保存在 private/device/android-cache-pac.*。
该结果不证明 EL1 密钥寄存器访问、macOS arm64e 加载和跨进程密钥切换已实现。

Actions 39931119921 已完整收集各模块错误，避免逐文件失败后重复构建。
公开 XNU 的普通 4 KiB 页表路径只提供 38/39 位用户 VA，无法直接承载 macOS 默认 47 位用户地址布局；
该路径的 commpage 断言揭示了实际配置冲突，不删除断言，也不缩小 macOS 用户地址 ABI。
SHENG 的 macOS 26 编译目标改为原生 16 KiB / 47 位布局及对应链接地址。
UEFI 实测 MMFR0=0x22200101122 的 TGran16 字段为 1；当前只作为能力声明，16 KiB 页表执行尚待新内核验证。
原有完整 sheng 4 KiB 硬件参考配置保持原样。
已将三个无条件 Apple CPU 头改为仅 Apple 平台引用，修复非 SPTM pmap 的真实声明和 panic 诊断引用。
六类旧源码/工具生成代码兼容告警保留为 warning，其余仍为 error；重新编译的机器层对象将恢复这六类 error。
归档失败时仍尝试编译机器层对象，分别记录失败，不把残留归档或个别对象算作内核成功。

Actions 39932752293 的 16 KiB 编译已消除用户地址布局断言，继续暴露四个未公开的 Apple AMCC 源文件选择。
按 UniXNU 的设备条件化方式为这些源文件增加独立选项，SHENG 不启用 Apple 内存控制器。
串口注册函数仅在对应 UART 后端存在时编译；没有为 sheng 虚构串口设备。
ArmCpu 的五个外部诊断/中断接口补齐声明，ArmDTPlatform 的复位函数标为 noreturn。
这两项适配只应用到独立驱动副本，固定 UniXNU 源码保持不变。
macOS 原生内核目标不再依赖无关的全量检查任务，仍执行当前源码的真实编译并保存失败日志。

Actions 39933736122 已编译通过 ArmDTPlatform 与 ArmCpu，真实对象部署目标为 macOS 26.5。
内核翻译单元没有新的源码错误；归档阶段失败在普通构建生成 `.filelist`，归档规则却要求 `.libfilelist`。
该构建仍记为失败，没有可执行内核和 macOS 实机启动结果。
归档规则已按 RC_ProjectName 选择实际生成的对象清单，保留普通内核编译语义，待后续必要构建验证。
已对照 Snapintosh 组织当前源码，路线差异、EL2/NV2 前提与 PAC 实现记录在 `docs/routes.md`。
继续工作以 16 KiB 实际页表执行和 arm64e 密钥生命周期为主，不再把清除编译告警当作启动路线成立。

新增独立 `ShengNativeEl1.efi`，以同一份 EL1 汇编执行区分性页表实验与五类 PAC 密钥切换。
QEMU 实际执行的 16 KiB 正对照、强制 4 KiB 回退负对照，以及 IA/IB/DA/DB/GA 切换和状态恢复均通过。
UEFI 应用已编译；候选沿用已实机通过的固件和厂商 DTB，使用 RAM FAT，不写分区。
这些结果尚未证明 sheng 的实际执行、47 位完整布局或 XNU task/thread 的 PAC 语义。

Actions 39937165999 已成功生成 macOS 26.5 原生内核归档，ArmDTPlatform/ArmCpu 对象编译通过。
当前仍无可执行内核，不将此结果视为 ABI 或实机启动通过。
第一轮独立 EFI 探针从 RAM FAT 选择后返回 Access Denied，屏幕照片确认尚未取得探针执行结果。
新版改用现有 FV 注册启动方式，固件 FV 与注册器均已构建；没有放宽全局镜像加载策略。
同时让所有提前返回的探针分支停留显示原因，栈映射检查仅覆盖实际使用范围。

FV 候选经用户确认自动复位，随后 Android ADB 恢复，槽 _a。尚未确认探针的最早入口画面。
Android 原因属性只报告 bootloader，pstore 读取被拒绝，不能据此归因为 16 KiB 或 PAC 异常。
新候选先停在 MMU 实验前，按键执行后再停留，下一次按键才进入 PAC。
MMU 汇编新增临时 EL1 异常向量与阶段记录；QEMU 未定义指令实测已恢复原页表并返回异常信息。
源码归档的符号清单另揭示新版 processor_start KPI 已改变，后续 SMP 需按真实注册流程迁移，不能换成返回失败的同名兼容函数。

后续实机照片已确认 FV 探针进入 EL1，完成执行区/栈的恒等映射检查，停在 MMU 实验前。
用户按电源键后没有可见变化；旧版未显示按键接收和汇编入口，暂不能区分输入未到达与 MMU 实验停顿。
新版枚举并读取各 SimpleTextIn 设备，照片确认 3 个输入设备、source=0/scan=0/char=13，最后显示 MMU probe starting。
因此输入已通，停顿位于 MMU 汇编及其返回路径；还不能归因为 16 KiB 不受支持。
后续探针参考 UniXNU DarwinEnter 的 framebuffer 标记，在 MMU 关键阶段直接填 0-F 像素格，避免依赖失效映射下的固件日志。
目前仍没有实机 16 KiB 页表或 EL1 PAC 密钥切换通过的证据。

最新实机反馈只有 0/1/2 绿色：关闭 MMU 后仍能执行，停顿在 4K 控制页表安装至 TLB 屏障完成之间。
固件原 TCR=0x280803518，探针构造值遗漏了现有 ArmMmuLib 保留的有效 TG1 编码；写 TCR 后也没有立即 ISB。
这两处已按固件实现修正，并细分标记 3 的控制寄存器写入阶段；是否解除实机停顿仍待观察。

修正版实机照片和用户补充显示：0/1 完整，2 只有细线，3 未亮。
因此修正之前“关闭 MMU 后阶段已完成”的推断，当前不能确认显示标记返回，更不能归因为 TTBR0 或 16K。
探针改用原本禁用的 TTBR1 窗口，以高地址 AT 做相同 A-D 区分，不修改 TTBR0/TG0、MAIR 或 SCTLR。
同一汇编在 M/C/I 开启、MAIR 槽 3 为 Normal WB 的 QEMU 对照中通过，实机仍待观测。
社区调查另发现高通早期 TrustZone 退出 Gunyah 的源码，记于 docs/routes.md；本机服务可用性尚未测得。

TTBR1 版（0e6d102）实机照片确认全部 0-F 标记、granule16=PASS 和 firmware-restored=PASS。
4K 有效控制、空叶控制、区分地址负对照及 16K 区分翻译均返回，未出现 trap。
这确认 sheng 当前 EL1 环境的实际 16K 页表遍历，不证明 16K 内核代码、完整 47 位布局或 arm64e 用户空间已能运行。
目前停在 PAC 实验前，结果另行记录。

同次实机 PAC 结果截图确认 bank-switch=PASS、flags=0x7fff 和 status=Success，已返回末页按键等待。
用户先报告自动重启，后提供重启前截图；以截图修正归因，不能把随后重启当作 PAC 测试失败。
由此确认启动核 EL1 的 IA/IB/DA/DB/GA 测试密钥切换、认证和固件密钥恢复，不代表 Apple 密钥派生或任务切换已实现。
KDP 的已有编译支持、传输阻断及符号要求记录于 docs/debugging.md，并已写入本地开发约定。
下一项独立探针在 47 位 TTBR1 的低端和预定内核高地址执行 16K RX 页，检查独立 RW 数据页和拒绝控制。

47 位候选（012d6fc）实机照片确认 walks=PASS、execute=PASS、controls=PASS、firmware-restored=PASS、status=Success。
返回 PC 分别为 0xffff800000004000 和 0xfffffe0007004000，独立数据页读回 0x5757，0-F 标记全部完成。
这确认启动核在现有 EL1 环境可遍历并执行 47 位 TTBR1 窗口的 16K 映射，代码写入和未映射地址负对照正确。
独立能力探针阶段结束；后续推进配套 macOS 26.5 XNU 的可执行链接、机器层 ABI 和 arm64e 生命周期。
尚未启动 macOS 内核或用户空间，也未验证完整 XNU pmap、EL0 地址空间和多核切换。

可执行内核阶段已启动 Actions 39945615555（a19e82d），目标为 macos26-kernel，尚无链接成功结果。
构建沿用配套 XNU 的完整链接规则，新增同版本 libdispatch firehose 构建，SHENG 不再索取不存在的 Apple SoC 支持归档。
ArmCpu 独立副本移除旧 processor_start 辅助线程，改由新版 ml_processor_register 的既有启动路径负责，未改固定 UniXNU 源码。
首启仍以单核为界；本次源码迁移不代表新内核 SMP 已通过。
保留实际链接错误和增量产物；链接成功后保留未剥离内核、UUID、dSYM，硬件/用户空间资格仍另行判断。
已对照当前 DarwinBoot 的 boot_args 字段与 12377.121.6 的 boot.h，布局一致；加载新版 Mach-O 仍待实际产物。
平板已回到 Android，ADB 核对产品 sheng、活动槽 _a。

Actions 39945615555 已执行真实内核链接，失败仅剩 ml_device_is_prod_fused、pmap_pending_preemption 和 tb_transport_startup 三项。
firehose 与编译器内核运行库已实际参与链接，CPU 注册迁移未再产生旧 processor_start 引用。
SHENG 补齐 UniXNU 的 ArmDTPlatform/ArmCpu IOKit 匹配项。
Apple 熔丝查询在 SHENG 排除，保留现有 fail-safe 开发状态，不伪造量产熔丝值。
pmap 在 SHENG 使用公开源码已有的 AST_URGENT 检查，仅排除缺失的私有调试包装；其余 SCHED_HYGIENE_DEBUG 保留。
SHENG 未提供 exclaves/AFK 传输，不注册依赖 Tightbeam 私有实现的初始化入口。
这些改动解决具体链接契约；并不声明硬件驱动或原版 macOS 组件 ABI 已通过。

Actions 39946670153（eb14e36）已链接出实际 macOS 26.5 SHENG 可执行内核，dSYM UUID 匹配。
实际 UEFI / DarwinBoot / QEMU 已进入 arm_init，记录 PC=0xfffffe0007bab8a4，MMU 开启，TG0/TG1=16K、T0SZ/T1SZ=17。
这不是 sheng 实机 XNU 启动或用户空间结果。
参考 Snapintosh 的保留控制台机制，新增原生字符出口日志和 panic 快照；同一写入代码的回绕、重入丢失及解码拒绝已通过。
该新增日志代码仍待 macOS 目标编译与实际内核执行；实机导出、重启后保留及 KDP 传输尚未接通。

修正上述 QEMU 入口结论：地址断点命中不等于 C 指令已执行。
首个 EL1 SP0 同步异常捕获 ELR=arm_init，ESR=0x02000000；现场异常向量字节实际来自 LINKEDIT 字符串，而非对应指令。
加载器只保证 2 MiB 的 VA/PA 同余，16K XNU 的启动 L2 块是 32 MiB，旧 PA=0x48004000 与 VA=0xfffffe0007004000 的低 25 位不一致。
新增 DarwinBoot 补丁保持 32 MiB 同余；该约束同时覆盖旧 4K 内核所需的低 21 位，不修改 XNU 指令来掩盖映射错误。
Actions 39948603742 的日志版编译失败于新日志 UUID 解析的 Wcast-align；改为有界 memcpy，不关闭诊断。
完整源日志改为独立小型 Actions 产物，失败时优先打印第一处真实错误。

32 MiB 同余加载器（5745be36）已在 QEMU 消除错误映射；现场异常向量与文件指令一致，实际执行到 panic。
配套源码 prng_random.c 的 ARM64 BOOTLOADER_ENTROPY_REQUEST_SIZE=4*64=256，旧树只有 64 字节，已为两套 DT 生成器增加显式 256 字节选项。
补足熵后，QEMU 首次 BRK 现场及匹配 dSYM 定位到 arm_vm_physmap_init 的边界断言。
实测 physmap_base=0xfffffdf0153a8000、physmap_end=0xfffffdf0353a8000、gPhysSize=512 MiB、ptov_index=2。
非 PPL 大地址分支没有为 PTOV 块对齐间隙留虚拟空间；SHENG 采用与源码另一分支相同的 PTOV_TABLE_SIZE * ARM_TT_TWIG_SIZE 预算。
预算只扩大虚拟 aperture 上限和对应页表覆盖范围，不增加物理内存；保留原边界断言。
Actions 39950123042 已编译链接日志版并生成 dSYM，但记录阶段缺失 map 文件：原变量 DEPLOYMENT_LINKER_FLAGS 不参与此链接规则。
改为显式传入附加原生链接参数，待下一次必要构建确认。

新增独立 native_log_reader：按观察到的真实加载 PA 与匹配符号计算范围，DT 显式保留日志 RAM 并禁用内建 UFS 控制器。
ARM64 PID1 编译、FAT 文件边界和主机捕获格式已通过；当前未部署 reader，不宣称重启后保留或 USB 实机传输通过。
locore 首次同步异常快照已加入目标源码，待目标汇编和实际执行；原 panic hook 保留格式化消息。
成功构建另上传只含可执行内核、map、dSYM 和 build.json 的小型产物，避免后续调试每次下载完整源码归档。

Actions 39951693129 已成功构建包含首次异常记录的内核，UUID F06BECA4-5F5A-35B8-9C5A-5B1B57DFE215。
QEMU 经真实 DarwinBoot 进入 C、完成 VM 初始化并启动 IOKit/NVRAM，取回 6852 字节原生控制台日志，无环形覆盖或忙写丢失。
首次同步异常 PC=0xfffffe0007a6bfa4、ESR=0x96000005、FAR=0x150，对应 crypto_random_kmem_ctx_size。
调用者 vm_map_store_crypto_init 读取尚未注册的 g_crypto_funcs；尚未进入 BSD 或 macOS 用户空间。
日志原始快照、寄存器、对应 dSYM 和 map 已保存在本地私有产物中。
已封装同版本 RAM 启动候选 c2c9f15c0ae9dd688509b5825b0507452adabdc1df1b9f1fd98954895996d9f0，未部署设备。
下一项是为原生内核接入真实 corecrypto 源码提供者，复用 UniXNU 的初始化时序，保留完整 POST。

标准 panic 缓冲区已在 QEMU 验证：DarwinBoot 只从已有 owned window 分配 512 KiB，经 `/pram/reg` 交给 XNU。
gPanicBase 正常初始化；原有缺失缓冲区提示消失，取回完整寄存器、15 层回溯及压缩 stackshot。
512 KiB 原始区的版本 8、CRC 和 UUID 匹配，panic 文本 3500 字节、stackshot 2314 字节。
原生控制台保留 11882 字节，无覆盖或忙写丢失。实机 RAM 跨重启保留、USB、KDP 传输仍未验收。

Apple 2026-05 corecrypto（9612a959，模块 26.0）631 个 C 源文件已完成 macOS 26.5 目标编译和命名隔离。
Actions 39954559619 停在构建器对 IOMallocData 的误判：它由 XNU 的 IOKit.exports 映射到实际 IOMallocData_external。
已按原导出表识别别名，不增加替代分配器；Actions 39955552708 继续真实链接及 POST。
该公开提供者没有填充 XNU 26.5 新增的 sized digest/HMAC 尾部，未宣称完整原版组件 ABI 已兼容。

Actions 39955552708 已链接包含 corecrypto 的内核；真实 QEMU POST 的 HMAC/AES/RSA/ECDSA/ECDH 等算法测试通过。
完整性与服务指示器测试失败，保持原始 POST 拒绝并生成完整 panic/stackshot，尚未注册加密函数表或进入 BSD。
完整性不再覆盖 XNU 启动时会修改的全部 __text：提供者代码迁入同一 RX 段中的独占 __cc26_text，按模块代码范围封装 POST 视图并生成 HMAC。
命名隔离从 C 宏改为汇编符号 pragma，保留服务指示器使用的规范 C 字符串；没有修改测试的判定或算法策略。
原串口初始化失败时 PE_kputc 会回退到 console_write_unbuffered，panic 又把同一字符发到同一控制台两次；新增 SHENG 判断跳过这次冗余镜像。
已失败和被替代的部署镜像清理 56 个文件，释放约 2.19 GiB；在用 Android 恢复备份、配套输入和调试现场保留。

Actions 39958185731（4636503）已成功构建；QEMU 中原始 corecrypto POST 全部通过，完成函数表注册和 PRNG 初始化。
内核 UUID 为 E1D86942-7CD8-3E8A-8A08-595CBD5D1117；该结果仅确认当前公开源码提供者的启动自检，不代表闭源组件完整加密 ABI 已兼容。
下一处实际 panic 是 kern_trustcache.c:584 的 `image4 interface not available`，尚未进入 BSD、launchd 或恢复界面。
已保留 512 KiB 原始 panic 区、匹配 UUID/CRC、2390 字节 panic 文本和 2620 字节 stackshot。
完整 panic 可从独立缓冲区取回，但此前去重改动让控制台回退路径只作缓冲写入，部分 panic 文字未及时进入字符日志。
新增 0021 补丁使该回退路径只执行一次无缓冲写入；补丁的实际目标编译和运行结果留待下一次必要构建。
匹配的 25F71 内核集合已确认包含 AppleImage4 和 AMFI；当前需要解决其 ARM64E fileset 的依赖、认证指针和原生加载契约，不能直接套用旧 ARM64 prelink。
已结束观察的 ESP 暂存另释放约 854 MiB；累计清理约 3.02 GiB，当前配套输入与有效恢复备份保留。

Actions 39961597801（9114516）构建成功；QEMU 再次完成原始 POST（131 ms），PRNG 已就绪。
实际 UUID 为 3BF08D8B-BD27-34B5-98AF-B40C3F752A8A，仍在相同 Image4 检查处 panic，未进入 BSD。
取回 6116 字节字符日志、完整 512 KiB panic 区和 2620 字节 stackshot；panic 区 CRC 与 UUID 匹配。
字符日志保留摘要，完整 panic 文本仍从标准 panic 区导出，不把 0021 当作完整文字镜像已通过。
只读分析匹配 BootKC 得到六个安全模块、12677 个链式指针，其中 7070 个需要认证；内核指针目标均存在同名导出候选。
当前普通 ARM64 的回调/虚表契约及未启用 PAC 的 XNU 链式加载器不能执行这些 ARM64E 组件。
上游可复用部分、实际 Image4 注册入口及后续契约记录于 docs/macos26-security.md；没有绕过安全初始化，也未部署平板。


Actions 39968730207（989144e）成功构建独立 ARM64E 内核，UUID 06C8764F-00D3-35AB-9069-A4B01E78F7F2。
QEMU 已进入 arm_init；首次异常为 static_if_init+0x40，FAR=0x1a92c0，标准 panic 区尚未初始化。
实际 Mach-O 是 MH_EXECUTE，包含格式 7 的 LC_DYLD_CHAINED_FIXUPS，__thread_starts 为空。
配套 XNU 对 MH_EXECUTE 只执行 rebase_threaded_starts，未处理该新表；static_if_init 因此访问了未还原的相对指针。
ARM64E 链接改为显式生成 __thread_starts，要求该表非空且不再输出 LC_DYLD_CHAINED_FIXUPS；由 XNU 原始路径完成还原与签名，不清除 PAC。
该修正及早期 framebuffer 控制台仍待新产物运行，不作为 ARM64E 完整启动成功。
同轮 CI 已实际命中 KDK 约 1.18 GB、ARM64E 编译产物约 172 MB，总耗时约 5 分 45 秒。
新增固定源码缓存，锁定两份依赖清单并在打补丁前保存；编译缓存继续按架构、工具链和适配输入隔离。

Actions 39970542294 在最终链接被 Xcode 27.1 明确拒绝：`-threaded_starts_section is no longer supported`。
撤销旧链接器选项，按配套 dyld/MachOLoaded.cpp 的格式 7 VM-offset 与 PAC 元数据语义，扩展 XNU 现有链式还原函数。
原生 MH_EXECUTE 在全局初始化前调用该函数，拒绝未解决 bind，认证指针继续由原 XNU sign_pointer 签名。
现有实际产物的 116829 个修复位置、其中 43757 个认证指针已被构建端有界读取；无外部 bind，目标位于内核布局内。
普通 ARM64 和已有 fileset 格式 8 路径保持原有处理；新内核执行仍待目标编译及 QEMU。

Actions 39972044375 未分配 runner，GitHub 注释为账户付款失败或支出额度不足；没有执行编译。
0002016 的格式 7 启动修正已推送，尚未得到目标编译或运行结果，未生成新的实机候选。
复查 39970542294 的 source-archive.log，缓存命中后仍编译 975 个翻译单元。
构建器改为只在头文件内容改变时更新暂存文件，KDK 展开路径固定为当前 profile，不再携带运行编号。
本地主机已确认不变头文件保留 mtime、变更内容正常替换；实际 CI 增量效果待账户恢复后确认。

本地 Clang 22 已将实际修改的链式还原函数编译为 ARM64E Mach-O，使用原 Mach-O/链式结构头文件及最小外部类型声明。
生成代码包含 PACIA/PACIB/PACDA/PACDB，没有移除认证；该定向编译只确认新增函数的目标语法与指令生成。
整颗 XNU 的 Xcode 构建、同版 QEMU POST/屏幕日志和 sheng 镜像封装仍未完成，等待 GitHub 账户恢复或可用 macOS 构建机。


Actions 39973422068（f6ba858）成功构建原生 ARM64E 内核，UUID EAD2C86F-E6BC-3D27-AA13-CA19EC0E76D2。
此轮已实际恢复固定源码、KDK 与 ARM64E 编译缓存；工作流的稳定路径在 runner 分配后的步骤中导出。
QEMU 处理格式 7 的 116829 个指针，其中 43757 个需要认证；内核继续完成 VM、IOKit/NVRAM 与全部 corecrypto POST（230 ms）。
原始 panic 仍为 `image4 interface not available @kern_trustcache.c:584`，尚未进入 BSD 或用户空间。
早期 framebuffer 文本控制台已实际显示完整 panic/回溯；字符日志 8801 字节，无覆盖或忙写丢失。
标准 panic 区 512 KiB 的 CRC/UUID 匹配，panic 文本 2390 字节，压缩 stackshot 2684 字节。
同版 sheng RAM 启动镜像已封装，SHA-256 7b69a7af4a642b7594ae7011d7577c0d786522eae438163900320d5c2d93179a，72015872 字节。
镜像仅用于实机原生内核与日志实验，预期停在上述 Image4 panic，不代表恢复界面可用；实机日志保留和 USB reader 仍待验收。
用户提供的 fileset/kext 参考截图没有配套源码，按机制参考；当前内核已含 csr_check，不重复引入配置。
后续真实原版 corecrypto 接入时必须替换现有源码提供者，避免两次注册/初始化 PRNG；不将常量表中的字节当作 BL 修补。

2026-10-24 首次部署此 ARM64E 镜像：ADB 确认 sheng / _a，fastboot 仍为 a，下载上限 768 MiB。
仅执行 fastboot boot，72015872 字节镜像发送成功，ABL 返回 Booting OKAY；未执行 flash、分区写入或槽位切换。
当前仅确认引导器接受镜像，实际 XNU 屏幕结果待用户回传。

实机回传仅见 DarwinBoot 绿色条，没有 XNU 控制台；该条由 DarwinEnter 绘制，不能据此认定 XNU 入口或 C 初始化已执行。
照片可辨 args PA=0x882A00000、panic PA=0x882A04000，窗口 512 MiB。
同版内核 VM 跨度为 0x19FC000，据此得 kernel PA=0x881004000、log PA=0x881DBC000，VA/PA 低 25 位均为 0x1004000。
读取器原先按连续低位内存限制地址，未覆盖 sheng 的实际高位 DRAM 银行；已按保存的 Recovery iomem 和 UEFI SMEM 范围限定为 0x880000000..0x8BB300000。
本次只读 reader 已构建，显式 DT no-map 预留日志与 panic 区、禁用 UFS，实际 USB 及 warm-reset 保留仍待运行。

只读 RAM reader 临时启动被 ABL 接受，但未出现 USB 磁盘；随后 fastboot getvar current-slot 正常返回 a，未取得 RAM 内容。
该结果不能区分读取器未启动、取样失败或 USB 链路未就绪；配套 Linux 的 qcom_glink_smem 和远端处理器为模块，当前读取器未提供完整 PMIC GLINK 启动链。
失败的 reader 部署镜像已删除，源码、输入和实际部署记录保留。
DarwinEnter 新增直接 framebuffer 交接标记：绿色为进入、蓝色为缓存清理结束、橙色为 MMU 关闭后执行。
这些都是加载器检查点，不作为 XNU 执行证据；后续用同一 ARM64E 内核区分交接阶段与内核阶段。

三段交接标记加载器已完成本地构建，实际固件 FV 中存在相应提示字符串；QEMU 同版内核再次完成 POST 与预期 Image4 panic，完整 panic 可导出。
新 RAM 候选为 5f96ecce756ea1445da944a6ae3525cd83059794be19bea5d94ea51e08aa6bbd。
发送 72015872 字节完成，但 boot 命令在 USB 断开时未收到最终状态；是否执行以实机回传为准，不将发送完成记作启动成功。
被替代的部署镜像、固件副本和已完成 QEMU ESP 暂存另删除 104582976 字节；当前候选、有效 Android 恢复备份与诊断记录保留。

该候选首次发送状态不明，随后一次重发收到 Booting OKAY；用户回传仍在 FASTBOOT 或黑屏后重启，没有确认进入 UniXNU。
重发前实际 current-slot 已为 b，与实验前的 a 不同；一次性脚本记录了变化却没有阻止发送，这处处理有误。
停止部署后，ABL 报告 a 的 slot-unbootable=yes、b 的 slot-unbootable=no；按 b 正常重启仍回 fastboot。
现有命令记录没有在此前执行 set_active；槽位标记改变的具体触发点未知，不能据此判断本版 DarwinEnter 停在哪一条指令。
经用户明确允许执行 set_active a 后，a 的不可启动标记清除，正常重启恢复 Android。
ADB 已确认 sheng、活动槽 _a、sys.boot_completed=1；本次恢复未刷写系统镜像。

新增 scripts/boot_native_experiment.py 作为后续原生内核部署入口，必须明确指定序列号、预期槽位和独立记录目录。
槽位不同、查询失败或目标槽被标记为不可启动时，发送镜像前拒绝；boot USB 断开或超时后只记录状态不明，不自动重发。
槽位变化、不可启动、USB 错误和超时四项定向测试通过，没有再次部署设备。
当前 macOS 实机进度仍是加载器交接曾出现绿色条；XNU 执行尚无实机证据。
QEMU 已完成 ARM64E 指针签名、VM、IOKit/NVRAM 和 corecrypto POST，下一处已知内核阻断仍是 Image4 接口缺失。

恢复 a 槽后的受控复测：Android 基线为 sheng / _a / boot_completed=1，fastboot 报告 a 可启动。
同一 5f96ecce 镜像收到 Booting OKAY，照片确认绿色、蓝色和橙色交接标记全部出现。
kernel PA=0x881004000、panic PA=0x882A04000；屏幕保留的 SecurityLock 与交接文字来自 UEFI，不是 XNU panic。
本次证明加载器缓存清理和 MMU 关闭后执行均已完成，仍未确认 XNU 入口或 C 初始化。
返回 fastboot 后槽位保持 a、不可启动标记为 no，正常重启恢复 Android；ADB 已确认 _a / boot_completed=1。

针对 XNU 早期低位异常向量只会循环、无法输出现场的缺口，新增 0023 和页内原生异常屏幕。
独立 ARM64E 汇编及 QEMU 实际故障注入通过：入口正常返回，复制后的 4 KiB 向量页捕获 BRK，ELR=0x40400018、ESR=0xF2000123，屏幕能显示寄存器。
该结果只确认新增异常路径；完整内核的目标编译与运行尚待完成，不作为 sheng 内核启动成功。

Actions 39982721882（82725c4）已构建含早期现场的完整 ARM64E 内核，UUID FD9D4990-B43E-3BC2-B02C-50AA7C34DDA1。
同版 QEMU 记录 XNU 入口状态 1，随后完成 VM、IOKit/NVRAM 和全部 corecrypto POST（235 ms）。
仍在 Image4 缺失处 panic，未到 BSD；8801 字节字符日志完整，无覆盖或忙写丢失，512 KiB panic 区 CRC/UUID 匹配。
保存于 out/macos26-early-exception-39982721882，原有 bsd_init 观察未命中属于已知 Image4 阻断。
新实机候选为 ee83d0f8768c64d63043e1d5940a1c1aa3f21414a6801a128254338b1255f296。
Android / _a 基线确认后仅临时启动，a 槽可启动，ABL 返回 Booting OKAY；早期现场实机结果待回传。
被替代的 5f96ecce 部署镜像和已结束观察的 ESP 暂存已删除，调试现场、对应 dSYM 与有效 Android 备份保留。

ee83d0f8 实机用户回传为绿色、蓝色两条，未见橙色，随后重启；没有早期 XNU 寄存器页。
返回 fastboot 后仍为 a 且可启动，正常重启恢复 Android；未切槽或刷写分区。
结果首先指向加载器 MMU 切换阶段，不能将这次重启归因于 Image4 或原版 kext。
检查发现 DarwinEnter 只清理 owned kernel window，而它自身执行代码位于窗口外，且未核对关闭翻译时所需的 identity mapping。
新增 0014：按 CTR_EL0 给出实际 cache line 大小，将交接代码写回 PoC；用 AT S1E1R 检查交接代码每页、内核入口、参数与 framebuffer 标记范围的 VA/PA 一致性。
非一致映射在 ExitBootServices 前拒绝并打印地址；原有绿色条提示中的“kernel entry”改为“loader handoff”，避免误判执行阶段。
该缺口是源码事实，是否解释实机停顿仍需实验。
同一 FD9D4990 内核经修正加载器在 QEMU 完成 POST 和预期 Image4 panic，日志与标准 panic 区完整。
当前候选为 6c98fe8cc170442741d77698a235c8995634935b72adcf9a055b88abfb06bc33，实机结果待回传。

6c98fe8c 实机照片确认三条交接标记与新内核的 XNU=0000000000000001 寄存器页。
这是 FD9D4990 ARM64E 内核实际执行 start_first_cpu、安装低位向量并绘制入口页的证据，首次确认本版 XNU 启动汇编在 sheng 实机执行。
尚无 XNU=2；入口页的 ELR/ESR/FAR 是进入时已有寄存器值，不作为本次异常原因。
寄存器页与原 UEFI 文本有重叠，后续改为完整背景覆盖；MMU 切换后的执行、C 初始化和用户空间仍未确认。
用户返回 fastboot 后 a 槽仍可启动，已发正常重启恢复 Android，无槽位修改或镜像刷写。

本轮新增 0024，补足控制台建立前的 MMU 开启同步异常屏幕，使用原生启动页表恢复 V=P 取指后显示原始故障寄存器。
背景完整覆盖，避免旧 UEFI 字符与新寄存器页重叠。
独立 QEMU 16K 高位执行测试通过：关闭 TTBR0 后触发真实 BRK，XNU=3，ELR=0xffff8000402000e0、ESR=0xf2000124，保存的 TTBR0=0、TCR.EPD0=1。
诊断开关关闭后，原异常分发正常执行；复制后的低位向量与 ARM64E 目标汇编同时通过。
该新路径尚待完整 XNU 目标编译及运行；未部署新实机镜像。

Actions 39987628332（fb141b0）已成功构建包含0024的ARM64E内核，UUID 75EEE56A-3EC5-3A1C-B6BF-55CAF49A0432。
同版QEMU完成VM、IOKit/NVRAM和全部corecrypto POST（222 ms），控制台建立后sheng_bootstrap_capture_enabled实际为0。
完整字符日志8801字节，无忙写丢失，512 KiB标准panic区CRC/UUID匹配，仍停在已知Image4接口缺失处，未进入BSD。
新实机候选为94f5fa427cc58ebb68608d467cfc89ef6fc767958ca24ce6304afdd6793d3314，按a槽基线进行RAM临时启动。
被替代的6c98fe8c镜像与完成观察的ESP暂存已删除，内核、dSYM、寄存器和panic诊断保留。

94f5fa42实机照片和用户回复均确认仍为XNU=1，没有状态2/3，未捕获后续异常。
kernel PA=0x881004000、panic PA=0x882A04000；入口ESR为0不能用来排除后续故障。
返回fastboot后a槽可启动，正常重启恢复sheng / _a / boot_completed=1，未切槽或刷写分区。
对照实际链接指令发现，原common_start在开启MMU前就安装高位VBAR，存在首次翻译故障无法到达高位异常处理器的窗口。
新增0025延后高位VBAR安装，并使保留的低位向量在MMU开启时转入无栈物理恢复路径。
定向QEMU实际破坏TTBR1并令SP=0后仍捕获取指异常：XNU=3、ELR/FAR=0xffff800040000000、ESR=0x86000005。
该结果确认诊断覆盖扩大，不证明这就是sheng当前停顿的原因；新完整内核尚待构建。

同一75EEE56A内核另按实机kernel PA=0x881004000、boot_args PA=0x882A00000进行QEMU原始启动观察。
实际到达arm_init第一条PACIBSP指令前，指令字节与启动参数均匹配；SCTLR=0xFC54793D，TCR=0x800226511A511。
TTBR0=0x8811C8000、TTBR1=0x8811CC000，未发生异常。
说明该高物理地址可由本版启动页表处理；不模拟UEFI入口状态、framebuffer或Gunyah，不能据此排除固件相关问题。
新增scripts/observe_native_bootstrap.py保存这项有边界的实际内核观察，临时flat映像运行结束后删除。

Actions 39990930289（63c05d8）完成0025内核，UUID A7ED53F3-6EF8-3635-B671-754E84E396FB。
该版高物理地址观察通过，完整QEMU继续完成corecrypto POST并停在已知Image4接口缺失处；控制台后的诊断开关已关闭。
用户要求检查Gunyah等组件后，补充外层EL2调试陷入对照：同一内核设置MDCR_EL2.TDOSA后，在XNU=1之后的OSLAR写入陷入EL2。
实际ELR_EL2=0x8815BA07C、ESR_EL2=0x622807E0、指令0xD510109F，EL1 ESR仍为0。
这是可复现的覆盖边界，不是实机Gunyah归因。新增0026跳过SHENG冷启动及reset入口的可选OSLAR硬件调试解锁。
该版尚待目标编译和同一EL2陷入策略下的对照；不改写固件分区，不声称已关闭Gunyah。

Actions 39992979541（3dc4360）成功构建0026，UUID C9819D72-7190-3DF2-877C-6F93C6F722F5。
保持同一QEMU EL2调试陷入限制MDCR=0x400，新内核实际从0x881004000执行到arm_init第一条指令，入口指令和启动参数匹配。
ESR_EL2=0，说明跳过早期硬件调试解锁能绕开此已复现限制；尚不能据此归因实机Gunyah。

同版完整QEMU继续完成corecrypto POST，控制台后关闭诊断开关，仍在Image4接口缺失处panic，未到BSD。
8801字节字符日志无丢失，512 KiB标准panic区完整，CRC与UUID匹配；现场位于out/macos26-debug-unlock-39992979541。
实机候选81b73787560593b12213d6a3ffead5faac9acb61998e4e1419880f0e99fc23a7已封装。
Android基线sheng / _a / boot_completed=1，随后a槽可启动检查通过，单次RAM临时启动返回Booting OKAY。
实机结果待用户观察，记录位于private/experiments/20261024-native-arm64e/skip-debug-unlock，不把ABL确认记作内核运行证据。
被替代的94f5fa42部署镜像和已完成QEMU的ESP暂存已删除，保留有效Android恢复备份及配套诊断。

81b73787实机照片与用户回传仍为XNU=1，未捕获状态2/3，跳过OSLAR没有得到新的实机进展。
不能将该结果归因于OSLAR或Gunyah。用户返回fastboot后a槽可启动，正常重启恢复sheng / _a / boot_completed=1。
新增0027在同一内核保留0–C阶段条，覆盖入口页返回、参数/栈、两组启动映射和TCR/TTBR/MAIR写入，直到SCTLR写入前。
阶段条只用于定位，不增加重复能力探针；C格通过也不证明MMU开启。
相同汇编头在QEMU执行后，实际像素0–C为绿色、D–F为灰色，最后阶段记录12；低位复制向量和MMU开启故障捕获仍通过。
完整内核目标构建及实际启动结果待完成。

阶段条异常页重绘会依据保留的最后阶段恢复绿色格，不清除已执行的历史；尚未标记使用UINT64_MAX。
旧构建39995936219已取消，修正版Actions 39996227603（2cbf178）成功，UUID 788CD617-EF82-3D2C-8055-DD0BCBF6DC2E。
同版实际内核在实机物理地址及EL2调试陷入限制下记录到C并到达arm_init第一条指令。
完整UEFI QEMU启动记录到C，完成corecrypto POST、控制台及完整Image4缺失panic，CRC/UUID匹配，尚未进入BSD。
候选fc15ef51eab369ccc52ab49d57ab471b71730150138b4063980c4bcd7fd09069已封装。
实机Android基线sheng / _a / boot_completed=1，部署时a槽可启动，单次RAM临时启动收到Booting OKAY；阶段条结果待回传。
被替代的81b73787部署镜像和已完成QEMU的ESP暂存已删除，实验记录保存在private/experiments/20261024-native-arm64e/bootstrap-stage-strip。

fc15ef51实机用户回复及照片确认0–C全绿，D–F为当时未实现的灰格，XNU仍为1。
实际已越过参数/栈、启动页表清零与建立、TCR/TTBR0/TTBR1/MAIR写入，停顿缩小到SCTLR写入前后的区间；仍未确认MMU开启后执行。
返回fastboot后a槽可启动，正常重启恢复sheng / _a / boot_completed=1，未切槽或刷写镜像。
新增0028：只给阶段条范围补临时Device identity映射，D/E/F分别标记首次MMU ISB、高位VBAR安装和高位C入口交接前执行。
映射就绪时D–F预先变蓝，真正执行到才变绿，避免将诊断映射失败误判为SCTLR卡死。
相同汇编头QEMU中实际使用该映射写出MMU开启后的D/F像素，低位复制向量、同步异常和关闭诊断开关后的原分发仍通过。
完整内核目标编译和实际设备反馈待完成。

Actions 39998530367（2b85f65）完成0028内核，UUID 03DC05D0-E804-36A9-97FE-027308746E1F。
同版原始内核按sheng物理地址、3048×2032 framebuffer几何执行到arm_init首条指令前，阶段F、16个实际像素全绿，保留MDCR_EL2.TDOSA限制。
boot_args PA按新内核末尾计算为0x882A08000，不再沿用旧版固定地址。该观察不执行C初始化，不代表实机MMU已通过。
完整UEFI QEMU完成corecrypto POST和控制台，诊断开关关闭，标准panic CRC/UUID匹配，仍停在Image4接口缺失处。
其800×600 GOP低于诊断页高度要求，阶段条映射跳过；封装分别绑定完整UEFI观察和同内核sheng几何的像素观察。
新候选762f7ddab8f5cc2f00a215324449e4af56046d1c6982ad1ddfcb97278f416248已封装，待实机D/E/F反馈。
旧fc15ef51部署镜像、失败观察的flat暂存及完成QEMU的ESP已删除，保留诊断和有效恢复备份。

762f7dda实机照片确认0–F全部绿色，XNU仍为1。首次MMU ISB、高位VBAR安装及高地址交接均已执行；尚不能据此确认arm_init函数序言或后续C初始化完成。
原照片及结构化结果保存在private/experiments/20261024-native-arm64e/post-mmu-stage-strip。
用户返回fastboot后a槽可启动，正常重启恢复sheng / _a / boot_completed=1，无切槽或分区写入。
新增0029在同一已映射行记录16个早期C阶段，青色与原汇编绿色区分，范围从重定位之前到arm_vm_init调用之前。
采用强制内联的直接写屏，不依赖签名函数指针、日志锁或尚未建立的控制台；单独保存C阶段值并由完整QEMU观察读取。
ARM64E对象编译无运行时调用，补丁与已准备的同版源码匹配。完整内核构建及实机C阶段结果待完成。

Actions 40001339282（d924ef5）成功构建0029，UUID 7ECEED9F-1220-3FA5-8182-FCBD95E8C7F3。
实际内核在sheng物理地址和原EL2调试陷入限制下到达arm_init首条指令前，汇编阶段F及16个实际像素全绿。
完整UEFI QEMU读取到sheng_bootstrap_c_stage=0xF，随后完成VM、控制台及corecrypto POST，诊断开关关闭，仍在Image4接口缺失处panic；512 KiB标准panic完整、CRC/UUID匹配。
共用C头的定向QEMU运行显示0/7/F青色，其余灰色，相邻像素未变；这项显示测试不代表实机C初始化通过。
候选88b607ff20b2a73462e86f7c4c158a9258b2d1d195903f70aa188505b8a92d1f已封装。
Android基线sheng / _a / boot_completed=1，a槽可启动检查通过，单次RAM启动收到Booting OKAY。实机青色阶段结果待用户反馈。
旧762f7dda部署镜像和本次已完成观察的ESP暂存已删除，恢复备份、dSYM、字符日志和panic现场保留。

88b607ff实机照片与用户回复确认C阶段0–F全青色，XNU仍为1。实际完成重定位/签名、保留日志、静态条件、CPU拓扑、启动线程、定时器和DRAM设备树读取，到达arm_vm_init调用前。
不能把显示停留直接归因于arm_vm_init内部；页表切换后旧identity framebuffer不可再访问，后续执行缺少可读标记。
返回fastboot后a槽可启动，正常重启恢复sheng / _a / boot_completed=1，无切槽或分区写入。
新增0030沿用UniXNU的VM入口/返回进度与framebuffer重绑定思路，分阶段记录VM页表建立/切换，再通过原生ml_io_map映射至多1 MiB的阶段行页面，观察到PE_create_console返回。
诊断物理指针在TTBR0撤销前停用，不修改原生页表切换策略；紫色像素只在写后实际读回时设置witness。完整QEMU目标构建和新实机结果待完成。

Actions 40059689947（513345f）成功构建0030，UUID 59C3AB6E-8EFC-3D7F-9501-257EA134FE1B。
同版内核高物理地址启动观察通过。完整UEFI QEMU确认C阶段F、VM阶段F，原生I/O映射的阶段行VA为0xfffffe000a003f80，B–F实际像素读回witness=0xF800。
控制台后关闭早期异常截获，corecrypto POST通过；仍停在已知Image4接口缺失处，512 KiB标准panic完整、CRC/UUID匹配，未进入BSD。
定向运行共用VM头确认阶段7后物理写屏指针为0，阶段8只更新保留记录，不再触碰旧identity映射。
新候选1d9ede2dd3818cfd1ed8b192d2e242b97f5d3051c89011af1cd4a6209f130557已封装；Android基线sheng / _a / boot_completed=1，a槽可启动检查通过，单次RAM启动收到Booting OKAY。
实机紫色阶段结果待用户反馈，记录位于private/experiments/20261024-native-arm64e/vm-console-stage-strip。
旧88b607ff部署镜像及本次QEMU的ESP暂存已删除，配套诊断、dSYM和有效恢复备份保留。

1d9ede2d实机照片与用户回复确认VM阶段0–F全紫，XNU仍为1。正式VM已返回，原生I/O映射、serial_init、KPRINTF启动、首条kprintf和PE_create_console均已执行并返回。
尚未得到可读实机文字，不能将旧入口ESR=0解释为后续无异常。QEMU同版截图已有完整文字panic，当前差异是实机文字输出。
返回fastboot后a槽可启动，正常重启恢复sheng / _a / boot_completed=1，无切槽或分区写入。
新增0031将已有保留日志镜像到独立、有界的原生I/O文字面板，复用XNU字体；不依赖视频控制台锁，固定首个panic原因，原RAM日志格式不变。
增加控制台后的函数进入/返回文字，覆盖到machine_startup入口；不再增加阶段色条。ARM64E目标定向编译通过，完整内核构建与QEMU文字结果待完成。

Actions 40061902792（6466ed7）完成0031/0032内核，UUID 02DC95BF-0E2F-338F-B603-8F00758EF931。
pexpert不提供osfmk源码包含路径，因此将固定XNU的原字体显式暂存到pexpert/arm；启动参数中的64位尺寸经过边界限制后再转为面板的unsigned接口，未关闭编译警告。
完整UEFI QEMU确认面板ready=1、字符数9083、实际像素读回witness=1，截图首行保留image4 interface not available @kern_trustcache.c:584，后续回溯未覆盖原因。
同版正式VM与控制台阶段F、corecrypto POST及完整标准panic仍通过；尚未进入BSD。实际高物理地址启动观察到arm_init入口，16个汇编阶段像素全绿。
新候选90ec47c969cc34116ec3639720f4f950a96a2c330aa4edc5269d2b27b4f20aa3已封装，Android基线sheng / _a / boot_completed=1，a槽可启动检查通过，单次RAM启动收到Booting OKAY。
本次实机验收读取文字面板的最后函数或panic原因，不再要求新增色条；结果待用户回传，记录位于private/experiments/20261024-native-arm64e/native-log-panel。
已删除被替代的1d9ede2d部署镜像和完成观察的QEMU ESP，保留dSYM、诊断日志、配套输入和有效恢复备份。

90ec47c9实机两张照片及用户回传确认仍为旧入口文字和紫色0–F，未出现新日志面板；不能据此判定实机也停在Image4接口。
记录保存在private/experiments/20261024-native-arm64e/native-log-panel，交接地址为kernel PA 0x881004000、panic PA 0x882A10000。
返回fastboot后a槽可启动，正常重启恢复sheng / _a / boot_completed=1，无切槽或分区写入。
新面板额外依赖有界的大块I/O映射与保留日志writer，现有阶段条未验证它们；当前无法区分绑定前停顿、绑定拒绝和文字不可见。
新增0033复用已通过的12行原生映射，直接显示44字符的末函数或首个panic摘要，不申请新映射，不等待保留日志writer；原始完整日志与标准panic仍保留。
面板参数拒绝、映射和绑定分别输出明确文字，后续函数及原有kernel_bootstrap_log消息共用该通路；首次panic摘要固定，避免被回溯替换。
定向QEMU故意保持writer占用且不启用完整面板，实际字体像素读回通过，panic摘要在80次后续状态消息后仍保留，12行映射之外的哨兵未变；完整内核构建与实机结果待完成。

Actions 40063035904（5ce1275）成功构建0033，UUID 0BF0A13A-743B-3B24-8042-7935A89F34CB。
同版内核高物理地址启动观察通过；完整UEFI QEMU短文字行witness=1，实际截图显示PANIC: image4 interface not available摘要，完整面板也保留相同原因。
C与VM阶段F、corecrypto POST、诊断关闭及标准panic完整性均保持通过，尚未进入BSD。新候选b4904504d337802d1265cd015b19660695f3033b1cee084455fedd82f2fd2af5已封装。
实机部署前Android仍为sheng / _a / boot_completed=1，记录位于private/experiments/20261024-native-arm64e/mapped-log-status。
单次RAM临时启动前a槽可启动检查通过，ABL返回Booting OKAY，无刷写或切槽。
被替代的90ec47c9部署镜像及本次QEMU ESP已删除，完整诊断与有效恢复备份保留；实机文字结果待回传。

b4904504实机照片和用户回传确认小字与旧阶段条混在一起，不能可靠读取；没有据此判定末函数或panic原因。
照片保存在private/experiments/20261024-native-arm64e/mapped-log-status。返回fastboot后a槽可启动，正常重启恢复sheng / _a / boot_completed=1。
0034将状态文字移至独立黑底区域：sheng从第608行开始，标题和摘要各32像素高，44列；旧阶段条仍在568–579行，二者不共用像素。
原VM诊断的一次原生映射同时覆盖两个区域，限制为2 MiB；不再另行绑定0031大面板。控制台初始化前后分别绘制状态，后续视频字符回调避免覆盖文字区。
共享渲染器按3048×2032、stride=12192定向运行，实际文字像素读回通过；阶段条重画、模拟清屏后重绘、writer占用及首个panic固定均通过，边界外哨兵未变。
sheng映射需求为1277952字节，小型QEMU几何为1769472字节，均在2 MiB以内。ARM64E定向编译通过，完整内核构建和实机结果待完成。

Actions 40064245546（01b1239）成功构建0034，UUID 85932C1F-1D24-340B-B242-0AD641626DC2。
同版内核高物理地址启动观察通过；完整UEFI QEMU确认独立状态区映射、字体读回witness=1、标题与首个Image4 panic摘要可读，无普通控制台文字覆盖。
旧0031面板保持ready=0，实际走0034的单次映射路径；C/VM阶段F、corecrypto POST、诊断关闭和标准panic完整性仍通过，未进入BSD。
新候选943db4197fe17b3fbe64152b9cebbf6e69319574b451d9c77115acc5e21d7c88已封装，实机部署前Android仍为sheng / _a / boot_completed=1。
单次RAM临时启动前a槽可启动检查通过，ABL返回Booting OKAY，无刷写或切槽。
记录位于private/experiments/20261024-native-arm64e/status-panel-layout；旧b4904504部署镜像及本次QEMU ESP已删除，实机文字结果待回传。

943db419实机新照片可清楚读取SHENG - BOOT LOG及SHENG: PE_create_console enter，未出现returned。原紫色F与旧入口寄存器不能继续作为本次控制台已返回的证明，实机尚未确认Image4或corecrypto阶段。
用户返回fastboot后a槽可启动，正常重启恢复sheng / _a / boot_completed=1。照片与结构化结果位于private/experiments/20261024-native-arm64e/status-panel-layout。
0035/0036将原RAM日志在arm_vm_init返回后立即镜像至独立六行区域，位于标题和末函数摘要下方；不等待PE_create_console，不再依赖单行函数名逐个定位。
一次有界原生映射同时覆盖阶段条、标题及连续日志，上限4 MiB；字体沿用实机已读到的2倍大小，最多88列，屏幕不足时按实际宽度限制。
接入控制台创建全段的原有调用边界，并在首个内核同步异常进入sleh时直接绘制ELR/ESR/FAR/SP；不改原异常分发，早期汇编RAM寄存器记录继续保留。
定向运行确认进入控制台前已有滚动文字、清屏后能从RAM尾部恢复；writer占用时仍显示首个异常，后续80条消息不覆盖四项寄存器，区域外哨兵未变。此项为共享渲染器测试，不是实机异常结果。

用户明确授权建立日志分区。root Recovery当前GPT确认sde尾部空闲，新增第78项macoslog，LBA 448512–464895，4096字节扇区，共64 MiB，FAT16标签MACOSLOG。
主备GPT、现有分区条目及当前boot_a/boot_b属性保留；未缩小userdata，未刷写启动/固件分区。最新GPT与待使用空闲区已备份至private/backups/20261024-macoslog-partition，写入后逐范围读回一致。
Recovery重新启动后识别/dev/block/sde78与/dev/block/by-name/macoslog，实际挂载vfat、写入OBSERVED.JSON并读回一致，已卸载。
OBSERVED.JSON仅为实机照片观察记录，不能当作原始RAM日志。当前XNU UFS写入、跨重启RAM读取及自动落盘尚未接通，日志分区本身不改变这些边界。

2026-10-24 六行实时日志的CI 40066276268已完成，QEMU保存11,366字节完整保留日志，配套UUID 8171796D-28EC-36BC-888D-3C54DB4C4B7F。corecrypto POST通过，仍在已知Image4接口缺失处panic，未进入BSD或用户空间。
QEMU暴露panic之后的同步异常会替换已固定标题，新增“先发生的现场保留”规则：panic后异常不覆盖panic；同步异常先发生则保留寄存器，后续panic只进入日志尾部。独立实际字体/写屏运行测试覆盖两种顺序，含sheng屏幕尺寸和六行滚动边界。
