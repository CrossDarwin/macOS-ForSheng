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
