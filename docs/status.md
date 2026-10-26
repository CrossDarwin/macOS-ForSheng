# 实施状态 - 2026-10-26

系统目标已改为配对的 macOS 26.5 / 25F71。旧 XNU 独立验证 EL1 硬件交接，不能作为 macOS 26/27 用户空间的替代内核。

| 项目 | 状态 |
| --- | --- |
| UniXNU、Snapintosh、q1n1、依赖与两套 Mesa | 已固定提交并获取，补丁保存在本项目 |
| 25F71 IPSW 与公开源码 | 完整 ARM IPSW 已下载且 SHA-256 通过；三套内核版本均匹配 XNU 12377.121.6，九项公开源码已固定并核对 |
| 25F71 KDK | Actions 39925158581 通过 Apple 包签名及 M1/T8103、Neo/T8140 内核与配对 DWARF UUID 检查 |
| 25F71 恢复卷 | AEA 解密完成；SystemVersion=26.5/25F71，launchd 与 dyld 均为 ARM64e；已在QEMU挂载恢复根卷并执行launchd |
| 原生 25F71 ARM64E QEMU | 原版launchd及恢复服务已运行；显式软件合成开发实验已完成10帧GOP复制；省略钥匙串初始化并关闭旧日志镜像的对照已运行到原版RecoveryOS Agent设备所有者查询，截图出现等待光标；尚无LanguageChooser窗口 |
| 原生 25F71 ARM64E 实机 | 原版launchd已运行，ISC三种角色卷、临时Data和模板复制已通过，后续恢复服务持续启动；WindowServer反复exit(1)，尚无图形Recovery证据 |
| 完整 26A428 IPSW | 旧目标参考；下载及固定 SHA-256 校验完成 |
| J700 kernelcache / ADT / SPTM / TXM | 四项哈希与上游客体配置一致 |
| 26A428 KDK | 下载哈希、Apple 包签名、T8140 内核及配对 DWARF UUID 验证通过 |
| ShengPreflight | 实机运行完成；照片已取得启动核寄存器、内存统计和 GOP 摘要；MP Services 不可用 |
| 上游 EL2 监控层 | 本地及 xcode-27 Actions 编译通过，仍为 A16 构建基线 |
| 完整 sheng UEFI | 本地构建及 FV 检查通过；fastboot 临时启动成功，菜单和探针输出已由照片及视频确认 |
| 设备备份 | 六个LUN主备GPT及引导分区保留；当前重分区前后GPT均已保存；userdata按授权丢弃，未备份 |
| 完整上游 sheng 配置 | 35 项与上游字节一致，19 步及两个外部归档、预链接全部通过，Actions 39919525158 成功 |
| 旧 XNU 完整配置实机 | 控制台、BSD 入口、BSD 缓冲区、IOKitBSDInit 前与 IOFindBSDRoot 前检查点均实机通过；Android 恢复到槽 a；不代表25F71通过 |
| 旧 XNU 完整配置 QEMU | 完整配置产物经实际 UEFI/DarwinBoot 执行到 bsd_init，4 KiB 页表；未启动用户空间 |
| EL1 参考内核 | XNU 10063.141.1 已在 Actions 39905217735 构建通过，使用 gzip 和备份中的厂商 DTB 后已进入 XNU；MMU 后 3 秒复位探针实机通过 |
| 加载器合成交接 | QEMU 实测 boot_args、ramdisk、trustcache、清零与关闭 MMU 交接通过；不是 XNU 启动 |
| macOS 实机启动 / 双系统 | 64 GiB macosroot已创建，配套BaseSystem写入并完整读回一致；剩余userdata重建后Android槽a正常启动；macOS实机BaseSystem及ISC挂载已通过；运行时保留日志写入macoslog并在重启后由Recovery读回已通过 |

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

2026-10-24 新增DarwinBoot 0015：在下一次加载内核前有界恢复已指定RAM，匹配macoslog完整GPT/块设备身份后通过固件文件协议保存；当前内核的实际分配PA和符号生成下一轮恢复请求。
保存原始日志、解码文本、原始panic区、请求及寄存器/CRC摘要；每个文件Flush后读回比对，最后提交DONE标记。旧捕获和未完成捕获都不覆盖；不存在固件文件协议、页已占用、地址不恒等、UUID不匹配时拒绝。
宿主运行实际保存代码并模拟EFI服务，覆盖自动PA登记、二进制往返、环形回绕、writer中断、丢失字节、错误UUID/GPT/CRC、页独占失败、映射失败、短写及读回损坏，现有Python解码器逐字节确认EFI文本。ARM64 UEFI编译通过；宿主测试使用合成RAM及临时文件系统，不是实机跨重启成功。
新增capture_persistent_log.py用于root Recovery只读导出并校验配套UUID；跨重启RAM是否仍在、sheng固件是否发布日志卷文件协议，仍需下一轮实机确认。屏幕六行实时日志继续保留。

2026-10-24 实机Recovery完成capture_persistent_log.py只读导出。该环境没有blkid，读取器改为读取并校验主GPT及FAT16首扇区，核对唯一GUID、类型、LBA和卷标后挂载。实际成功导出既有OBSERVED.JSON并卸载；当前尚无CAP目录，不能视为RAM恢复成功。

2026-10-24 CI 40067791502完成。QEMU最终图的整图预览一度被误读成黑屏；重新读取PNG像素并放大原图确认SHENG标题五个字符、Image4完整panic行和末尾日志均可读。未提交的0037停机重绘方案撤回，原停机流程保留。打包新增真实截图标题逐字符像素检查，避免只依赖内存中的witness。

2026-10-24 专用卷日志版已临时启动，fastboot返回Booting OKAY，a槽且slot-unbootable:a=no。候选镜像64ccc5cfeeda78c7356be8f89c3c27d0d28db4a1ae3beee25db8dd884a4c499e，72,019,968字节；XNU UUID C4188A40-101E-3959-91D8-64E6FD648791。最终QEMU原图标题五字均有实际白色字形，完整panic CRC/UUID及11,366字节日志通过；高PA sheng尺寸交接到C入口、16格实际像素通过。
实机当前等待读取MACOSLOG recovery/next及六行面板。仅确认ABL接收镜像，尚未确认固件文件写入或RAM跨重启恢复。部署记录位于private/experiments/20261024-native-arm64e/persistent-log/deployment。

2026-10-24 专用卷日志版实机照片首次读到panic RAM zero enter之后的完整异常文字。PC 0xfffffe0007d0c088与本轮UUID C4188A40-101E-3959-91D8-64E6FD648791的bzero+0x48匹配，文件字节23 74 0b d5为dc zva,x3；LR去除签名后位于PE_create_console调用附近。Invalid kernel stack pointer来自早期Data Abort的栈检查分支，不能单凭该提示认定栈本身已损坏，原始ESR/FAR尚未读到。
0037仅将SHENG的panic区域初始化改为显式有序标量访问，不改通用bzero、页表或信任链；同时在invalid-stack入口记录原始异常寄存器，保留后续原处理。宿主验证0–255字节、8种起点及完整512 KiB边界，ARM64E生成代码没有DC ZVA或memset调用，包含dsb sy。映射属性/原始异常类型仍待下一次硬件现场确认。
本次Recovery只读导出再次确认macoslog只有OBSERVED.JSON，既无NEXTLOG.BIN也无CAP目录。照片recovery=Not Found、next=Not Found，UEFI卷发现/访问尚未成功；未取得自动RAM落盘日志。厂商logfs、xbl_sc_logs及rawdump头已只读保存，它们不能替代当前XNU日志。

2026-10-24 panic区域标量清零修正版CI 40070434490通过，内核UUID 66B40866-E424-3221-B3F2-A02D6F2AB308。实际链接函数sheng_zero_panic_region使用strb/str wzr与dsb sy，没有DC ZVA。QEMU读到panic RAM zero returned、控制台获取成功和corecrypto初始化完成；停止原因仍是Image4接口未接入，完整panic的CRC/UUID匹配，屏幕标题与原因可读。相同内核的sheng高PA交接、C入口及16个阶段像素通过。候选32e3a9700efe14aefcc872ee98e15ff8e5361f89c11588d6b4bdab0bb2038945已封装，实机清零修复尚待验证。

2026-10-24 用户视频确认清零修正版实机到达kern_trustcache.c:584的image4 interface not available，与QEMU停止点一致。首次panic摘要持续可读，原来的panic区域DC ZVA异常不再阻断；未进入BSD或用户空间。原始视频、最后画面及摘要保存在panic-io-zero/hardware-result。被替代的两版部署镜像已删除，恢复备份、dSYM与日志保留。

2026-10-24 原版安全组件QEMU集成：CI 40075022559通过，UUID 8E5415E1-ECF6-361D-A502-DE18C23B24E3。预链接保留认证指针，由XNU格式7链完成签名；原版corecrypto只初始化一次、完整POST通过、PRNG就绪。原版AppleImage4启动、注册真实接口并加载MAC策略，旧Image4缺失阻断已在QEMU越过。额外注册入口造成的重复注册已从生成元数据移除。当前停止于kern_trustcache.c:589的amfi interface not available，AMFI和CoreEntitlements接口仍为0。组件候选仅供QEMU，尚未部署sheng；日志、panic和截图保存在image4-relink。

同版内核接入原版amfi_register_mac_policy后，QEMU确认AMFI和CoreEntitlements真实接口均非空，AMFI策略加载，trust_cache_init及machine_lockdown完成。当前阻断转为平台驱动匹配失败：Unable to find driver for this platform: xiaomi,sheng。仍未进入BSD或用户空间，未对平板部署。

0044修正内建ArmDTPlatform的匹配表，保留device-tree并增加xiaomi,sheng。XNU的IODeviceTreeAlloc会把根服务名称改为compatible，而IODTPlatformExpert::probe通过IODTCompareNubName匹配name、compatible、device_type及model；旧匹配项未覆盖当前根服务。只扩展本平台的已知兼容字符串，不移除IOPanicPlatform或平台配置检查。新增QEMU读取现有平台配置、CPU、设备nub及NVRAM计数，构建与启动结果待验证。

同轮QEMU截图暴露面板误报：sleh_synchronous入口把随后由VM恢复的内核缺页也固定为首个异常，后续平台panic因此无法替换标题。0045移除普通同步异常入口的固定显示，将寄存器显示放到panic_with_thread_kernel_state的致命路径；SP1及invalid-stack的致命入口、汇编首异常RAM记录和原有异常恢复逻辑继续保留。该修正与0044共同构建，待QEMU截图确认。

CI 40076449616通过，UUID 51CEF8AA-71E7-3299-A98E-8BCF4425EA21。QEMU四个安全接口均位于对应原版组件映射内，信任缓存与lockdown继续通过；平台和CPU计数仍为0，仍停在IOPanicPlatform。实际链接字节没有ArmDTPlatform/ArmCpu personality，只有原有IOPanicPlatform：KernelConfigTables.cpp不包含board_config.h，SHENG宏在此未定义，0011和0044整段被排除。0046改用编译器已有ARM64_BOARD_CONFIG_SHENG，并在链接后检查真实产物必须含两项驱动匹配表与sheng兼容名。实际源文件预处理正负对照通过。

0045后的实际截图不再误固定可恢复缺页，但暴露关联问题：汇编原始异常已将RAM头panic_state设为3，后续sheng_log_panic的RAM头CAS失败，导致真实panic标题也未固定。现将屏幕首个致命现场的固定与RAM头写入分开，原始异常头继续保留；后续panic摘要与完整文本仍写入环形日志。实际共享渲染器定向运行确认state=3时真实panic固定、80条后续日志与嵌套panic不替换它，致命同步异常先到时仍保留寄存器。


2026-10-24 CI 40077286611通过，UUID 5428C76C-296B-3243-BE7B-E95BCE5257E9。实际链接产物包含ArmDTPlatform、ArmCpu及sheng兼容名。QEMU确认四个原版安全接口均落在各自组件映射内，平台配置、CPU注册、GIC就绪均为1，创建3个设备nub并启用NVRAM代理；已命中bsd_init且匹配当前指令字节。继续运行读到BSD版权文字与MAC Framework successfully initialized，确认BSD函数体已执行，尚未到根设备查找或用户空间。

同一候选首次继续运行在sleh_irq+0x48发生IA认证失败，x8为0。后续只读调试确认ml_install_interrupt_handler实际执行，向启动CPUdata+0xd8安装非空的已签名IOCPUInterruptController回调。对该槽设置写监视点后，回调未变化，IRQ故障也未复现；这轮继续到pthread_shims.c:319的pthread kernel extension not loaded。两次时序不同，不能据此宣告IRQ修复。原panic区、寄存器、完整日志及监视脚本保存在private/experiments/20261024-native-arm64e/image4-relink。实际致命异常页和普通panic页均已显示正确的首次现场。


原版pthread实验候选SHA256 96f29608afc48c052fb520d470f1e38a32bcd4f37d0389113e7eacdb81ddbcc6，UUID沿用40077286611。QEMU确认com.apple.kec.pthread依赖解析、真实module start成功，pthread_functions=0xfffffe000a896fc0位于原版线程组件映射内；尚未证明pthread_init及线程系统调用完成。继续运行仍复现IRQ空回调，启动CPUdata+0xd8实际读回0，故不能部署。


只读断点确认根因时序：ArmCpu::enableGic入口的启动CPUdata中interrupt_handler为0，实际调用链为ArmCpu::start -> ml_processor_register+0x1d8 -> processor_boot -> cpu_start -> cpu_machine_init -> PE_cpu_machine_init -> initCPU。旧驱动移植自较早XNU，先注册CPU再安装IOCPUInterruptController回调，且返回后重复调用initCPU。machine-cpu-interrupt-order.patch将启动CPU控制器初始化、回调安装与动作注册移到ml_processor_register之前，预先设置CPUNumber，删除多余initCPU；次核路径和PAC认证不改。补丁在前两份现有适配补丁之后应用，实际运行修复仍待新CI内核验证。


CI 40080070590构建成功，原生内核UUID 57B67A30-0E1E-3738-83EC-B3A3D5BF148D。附加配套pthread后的候选SHA256 fafec23152fe648a8944b9858bcb2244f8b205ed8abfe8d8e0c5c0c421b1e237。QEMU实际处理12次定时器中断，启动CPUdata+0xd8保持非空已签名回调，pthread函数表注册有效；越过原空IRQ回调错误，停在BSD的dtrace_postinit路径所触发的_unsafe_kernel_text_initialized断言。尚未到根设备查找，未部署实机。

该断言的原始ml_unsafe_kernel_text_init只有在/chosen存在4字节kernel-ctrr-to-be-enabled时才完成。两个生成器未提供此属性。新增native_devtree.py在本项目生成树上发布0，准确表示当前EL1未启用Apple CTRR，不声称具备Apple锁定硬件；XNU页表权限和原断言不改。QEMU观察器与未来硬件封装共用此输入修正。实际生成DT的插入、幂等、截断、尾部数据及矛盾CTRR声明检查通过，实际运行结果待下一轮观察。


同一40080070590内核补齐真实CTRR启动状态后，QEMU命中IOFindBSDRoot且当前指令字节匹配，16K/47位页表生效；已处理16次定时器中断。BSD的dlil/ifnet创建线程已实际调度，Skywalk自检通过，越过线程提供者与文本状态初始化阻断。原版Image4/AMFI/corecrypto/pthread均保持真实注册。此处是根设备查找入口，尚不代表找到磁盘、挂载APFS或执行launchd；未部署sheng。完整日志、寄存器与可读屏幕已保存image4-relink/macos26-security-native-text-live-40080070590。


继续执行IOFindBSDRoot后，完整日志明确等待IOMedia，默认匹配Content=Apple_HFS；本次没有提供块设备，函数未返回，未发生新的panic。下一段需接入真实只读块设备，并按已验证BaseSystem的APFS卷UUID选择根卷，不能沿用默认HFS选择。

原版IOStorageFamily依赖多出的__LINKINFO/__symbolsets只读段已纳入ARM64E封装，保留地址布局与原数据，内嵌段头的实际文件偏移已核对。附加APFS及其依赖的候选SHA256 38de20a179895c80094347fe6e287be39ce04ccbf5b1af304a26ea8df8da1984在QEMU再次到IOFindBSDRoot，处理15次定时器中断。日志确认APFS 2811.120.14、IOStorageFamily 2.1已注册为可加载模块；没有module start或磁盘I/O证据，不能据此宣称APFS已运行。尚需NativeVirtioBlock的26.5/ARM64E实际ABI接入、卷发布及根挂载，sheng则需单独验收UFS路径。


2026-10-24 存储接入：NativeVirtioBlock沿用固定UniXNU源码，以配套IOStorageFamily公开头和当前XNU编译配置构建独立kext，依赖原版IOStorageFamily。首轮缺少TargetConditionals.h，补入实际SDK头；第二轮普通bundle不接受arm64e.kernel对象，依据Apple ld64的kext模式改为-kext/-kexts_use_stubs，未更改对象ABI标记。CI 40082799111成功，实际产物MH_KEXT_BUNDLE、cpusubtype=0xc0000002，346个导入，DATA/DATA_CONST均为格式7链。

独立模块与原版IOBlockStorageDevice的实际虚表均为326槽，PAC参数逐槽相同，25处为驱动覆盖。唯一继承差异是第16槽：公开源码保留_RESERVEDOSMetaClassBase3，配套二进制使用OSMetaClassBase::Dispatch。实验绑定器只在本驱动实例及MetaClass对应的该槽改接内核现有真实Dispatch；无关保留槽、函数实现和PAC参数不改。C++签名比较使用实际解码后的类型，正确处理probe中S_与显式类名的等价编码。首轮完整封装已通过此检查，因原生头部只有400字节余量，新增映射命令放不下而拒绝输出；链接参数已增加0x2000预留，待新CI产物。

配套BaseSystem UDIF已按其Copy/Zero2描述重建完整GPT/APFS只读QEMU输入，1577092608字节，SHA256 6199e53d3cf60c59790e507851ef48141dbfa23875fdde5e838446984ed56881。UDIF六张表的实际CRC及GPT头CRC通过；Zero2按格式不参与表CRC，完整原始盘SHA256仍包含这些零区。7z从重建盘读回SystemVersion，确认26.5/25F71。实际QEMU导出的VirtIO FDT已转换，根卷匹配808EAC5E-8275-478D-814C-2229D8EB8D07。尚无驱动实际扇区读取或APFS挂载结果，未对sheng部署。

### NativeVirtioBlock首次实测：VM接管遗漏独立段

CI40083871388已成功构建带头部预留的原生ARM64E内核与独立NativeVirtioBlock。
配套25F71 BaseSystem已还原为只读raw磁盘，GPT与APFS卷身份通过输入校验。
首次QEMU实测尚未进入驱动：启动期kalloc_type_view_copy访问驱动__DATA_CONST时异常，
FAR=0xfffffe0009cb4b88，新驱动代码、数据的GDB读取均返回E14。
源码确认arm_vm_prot_init只映射固定KC段名，新增__NVB_*封装段没有进入接管后的页表。
因此这次没有磁盘读取、根卷挂载或launchd进展，原有BSD入口基线仍有效。

补丁0047为独立段增加严格按段权限的VM映射：代码RX、数据RWNX、
DATA_CONST在初始化时可写并在最终保护时改为RNX，同时映射IOStorageFamily的只读LINKINFO。
采集器现将E14等不可读结果保留为unavailable_globals，不再将其误当十六进制数解析；
已有快照可以离线重新解码，不重复启动QEMU。修正内核CI40084664897构建通过。
证据保存在private/experiments/20261024-native-arm64e/virtio-storage/unmapped-40083871388。

### QEMU实际块设备读取已通过

CI40084664897内核UUID01273EEF-6B10-3279-86C6-748ABB6C39A8。
封装SHA256 ba3d16fc4dad26ceea697ad54000fb971984015acb49bcdaf88f8483503f472b。
正常OSKext加载并启动原版IOStorageFamily，注册IOBlockStorageDevice、IOBlockStorageDriver、
IOGUIDPartitionScheme、IOMedia等实际类，然后启动独立NativeVirtioBlock。
其真实start路径经VirtIO队列完成512字节读取，ready=1、read_requests=1、
read_failures=0、capacity=3080259扇区、实际MMIO=0xa003e00。
内核对读回内容计算的SHA256为432967e802fe148ef1cb478821b47388fc8721bb38cb4a04f57067cc676039c7，
与配套只读磁盘首扇区一致。断点处指令字节、16K/47位页表及安全组件指针检查通过。
这确认VM映射修正和实际块设备读取；不等于APFS挂载、launchd或sheng UFS已通过。
证据保存在private/experiments/20261024-native-arm64e/virtio-storage/firstread-40084664897。

### APFS识别配套恢复卷，原策略拒绝未认证根卷

同一CI40084664897候选继续运行到实际APFS挂载，IOGUIDPartitionScheme与APFS均正常加载。
121次块设备读取成功、失败0次，APFS识别disk1s1、macOS Base System、4096字节块和xid105。
随后因缺少root-snapshot-name及个性化根认证payload，报Need authenticator(81)，
panic为The global payload bytes pointer is NULL @apfs_vfsops.c:2893。
实际512KiB panic区已读出，头部CRC与当前内核UUID一致，包含5901字节压缩stackshot。
这证明实际GPT/APFS读取与卷识别，尚未完成根挂载或launchd。
证据保存在private/experiments/20261024-native-arm64e/virtio-storage/root-auth-40084664897。

配套kern_csr.c明确支持/chosen/asmb的lp-sip0(u64)与lp-sip1(u32)。
新增--qemu-development-root仅对显式QEMU实验树设置sip0=0、sip1=1，
交由原有csr_bootstrap生成CSR_ALLOW_UNAUTHENTICATED_ROOT，不修改APFS代码，
不放开其他SIP位，不修改真实磁盘，也不进入实机封装。默认路径继续原认证策略。

### 根卷选择继续取证

CSR对照实测csr_config=0x800，但APFS仍在同一缺少payload处拒绝，不能称为绕过成功。
只读7z检查实际恢复卷：SEALED_VOLUME、num_snapshots=0。
这份BaseSystem没有可填写的真实命名快照，不填造root-snapshot-name。
从同一25F71 IPSW提取BaseSystemVolume的csys IM4P，核对j313ap各BuildIdentity摘要，
得到208字节原始root-hash payload，SHA256 a5d19735a248f0926caa92805f24e4576e4911eb0af80f76f4fcdebcbf0e4052。
参考Snapintosh/probes/ramdisk.py，原始payload通过/chosen/secure-boot-hashes/
system-volume-auth-blob传入APFS，同时声明实际recoveryos环境。
新脚本prepare_macos26_root_hash.py核对配对磁盘SHA256和原IPSW Manifest后提取，
输入摘要检查不等于已有个性化IM4M签名，运行结果仍待实测。

### 恢复根卷已实际挂载，进入init程序装载入口

给VirtIO驱动的实际IOKit personality补上Protocol Characteristics：
Physical Interconnect=Virtual Interface、Physical Interconnect Location=External。
这与IOStorageFamily公开常量一致，配套APFS的nx_is_virtual读取同一属性，
先前漏报时设备被当作内部系统盘并强制寻找本不存在的命名根快照。
原版APFS代码保持原样。

实际候选SHA256 eabed116ad70800359e8407532ce1e97a3afe7530475d1b869eef413e9f98be7，
内核UUID01273EEF-6B10-3279-86C6-748ABB6C39A8。
QEMU输出mount-complete volume macOS Base System，卷UUID与输入一致，
8520次磁盘读取成功、失败0次，随后完成BSD根卷流程与swap初始化，
断点实际命中load_init_program，指令字节及16K/47位页表检查通过。
根哈希原始数据已导入；本次采用显式QEMU开发CSR策略，不能称为个性化生产启动。
尚未执行launchd，下一观测点跟随thread_setentrypoint传出的真实EL0地址。
证据保存在private/experiments/20261024-native-arm64e/virtio-storage/mounted-40084664897。

### PID1装载失败已定位到文件压缩类型8

挂载根卷后，真实PID1/init执行load_init_program，尝试/sbin/launchd。
原生decmpfs报告tried to access a compressed file of unregistered type 8，
读取返回ENOTSUP(45)，随后Process 1 exec of /sbin/launchd failed。
因此尚未命中thread_setentrypoint或执行用户态代码，不将装载入口当作launchd运行。
下一候选补入同一BootKC的com.apple.AppleFSCompression.AppleFSCompressionTypeZlib
及自动解析出的真实依赖，保留原文件压缩内容，不在宿主改写系统盘。
证据保存在private/experiments/20261024-native-arm64e/virtio-storage/init-compression-missing-40084664897。

压缩组件封装扫描发现三处疑似跨模块分支，实际均为__text内的汇编常量表。
配套模块UUID EE081FA4-270B-3359-9DFD-61B9D6DBFAB1：
LZ4的528字节SIMD shuffle/步长表由前方ADR引用，
Adler32的40字节向量权重/模约简常量位于RET后的数据区。
扫描器仅对该UUID、固定段内偏移、完整SHA256和紧随的BTI函数边界匹配时排除数据，
所有真实指令继续原有检查。封装候选422f457e7254553b44f8ffffbf0327679cad9095f006c435100252389099d8c2，
143044个格式7指针、62232个认证指针，指令阻断0，尚待运行。

### 原版dyld首次在EL0实际执行

加入原版AppleFSCompressionTypeZlib后，不再报压缩类型8未注册，PID1成功装载程序。
QEMU命中thread_setentrypoint(x1=0x1031289c0)，随后只读断点观察到同一EL0入口，
PSTATE=0，16字节指令e00300911fec7c921d0080d21e0080d2与配套/usr/lib/dyld
文件偏移0x49c0逐字节一致，实际slide=0x103124000；launchd文件没有这段入口字节。
实际单步完成5条用户指令，随后跳到dyld 0x1e2b0位置触发取指缺页进入正常EL1向量，
不将尚未处理完的缺页当成已证实崩溃，也不把16次混合EL0/EL1单步全计为用户执行。
这证明PID1的dyld用户态已进入；尚未证明dyld初始化完成、launchd LC_MAIN运行或UI可用。
下一次观察由真实启动栈中的Mach header和原版launchd的LC_MAIN(95360)确定目标，
等待主函数及其首条指令完成，不修改进程寄存器或跳过执行。
证据保存在private/experiments/20261024-native-arm64e/virtio-storage/dyld-entry-40084664897。

### dyld完成缺页返回并进入libignition

未单步打断的同一候选继续运行，输出Darwin Ignition Sequence Version 1.0.0、
libignition-58及其arguments/ignition level等真实用户态日志，证明此前取指缺页被处理。
实际启动栈argc=1，主程序Mach header=0x104ccc000，
由原版launchd LC_MAIN确定目标0x104ce3480，120秒内未命中。
无panic正文；截止时CPU处于内核空闲线程。shared_region_check_np曾报告
vm_shared_region_start_address返回0x1，尚不能仅凭这一行断言是致命错误。
下一轮采集init开始后的有界Unix/Mach系统调用，定位实际等待对象和共享缓存流程。
证据保存在private/experiments/20261024-native-arm64e/virtio-storage/libignition-40084664897。

系统调用观测首次被旧工具的ARM64保存帧检查拒绝，未产生新的内核panic。
配套thread_status.h定义ARM64的arm_saved_state64为72个u32，
HAS_APPLE_PAC的ARM64E另有jophash，计数为74，前部通用寄存器布局相同。
集成补丁0016为GDB采集器提供显式72/74选择，按所选内核ABI读取并严格检查，
保留默认72的旧参考用例，不把格式错误解释为运行失败。

### 已定位dyld的实际Image4等待

修正ARM64E保存帧后，同一候选采集到51次真实Unix/Mach系统调用，未耗尽采集预算。
PID1打开/dev/null和/dev/console，输出原版libignition日志，随后查询
security.mac.img4.ignition_blob，实际MIB为[101,101,118,100]。
最后一次调用在41.954秒进入，120秒截止前没有后续调用，CPU处于内核空闲线程，无panic正文。
这将当前阻断缩小到ignition数据读取等待；launchd的LC_MAIN仍未命中。
证据保存在private/experiments/20261024-native-arm64e/virtio-storage/ignition-sysctl-40084664897。

配套dyld的DyldDelegates.h已定义commpage bit3为skipIgnition，
DyldProcessConfig.cpp由此控制ignite调用。UniXNU也在开发启动中使用同一机制。
补丁0048仅在SHENG的DEVELOPMENT/DEBUG内核、显式-sheng-qemu-no-ignition、
实际VMM标识及CSR_ALLOW_UNAUTHENTICATED_ROOT同时满足时发布该位，
不伪造Image4返回数据。观察器要求同时指定QEMU开发根策略和配对root-hash，
并采集开关是否真正执行及dyld_flags值。CI40088447141已构建通过，
候选SHA256 f1ddc71d14a8b22ba40c29c5f47176f59605606f5b5d1d794881c7de4df3a435，
硬件验收状态保持false。实际QEMU采集到开关标记1、dyld_flags=0x9，
不再进入ignition等待。dyld实际读取全部五个arm64e共享缓存文件，
继续产生488次系统调用，随后用户态PAC认证失败：
EXC_ARM_PAC_FAIL(0x105)、指令字0xdac11a30、退出原因namespace28。
launchd LC_MAIN仍未命中，不能把共享缓存读取当作launchd启动。
完整panic、stackshot与系统调用保存在private/experiments/20261024-native-arm64e/virtio-storage/no-ignition-40088447141。
观察器新增handle_pac_fail检查点，在终止PID1前采集真实EL0保存帧。

### 用户态PAC异常现场已取得

handle_pac_fail入口停止时，实际ESR=0x72000002，保存帧flavor21/count74，
CPSR=0x60000000，确认异常来自EL0。PC=0x102fcce88；实际指令字节
301ac1da080240f9与配套dyld文件偏移0x20e88一致，第一条为AUTDA x16,x17。
x16=0x1b5fd4d88，是没有PAC位的虚表地址；x24=0x1b5fd4468为helper对象，
x17=0x9abf0001b5fd4468为对象地址混入0x9abf的认证discriminator。
配套dyldMain.cpp的prepare正在取得libdyld __helper对象并调用version()，
尚未到launchd主函数。完整寄存器保存在private/experiments/20261024-native-arm64e/virtio-storage/pac-state-40088447141。

当前实际内核反汇编确认ml_default_jop_pid返回0，原始共享缓存签名代码在jop_key=0时
只重定位地址，不调用pmap_sign_user_ptr。现有SHENG原生PAC补丁只完成EL1；
ml_enable_user_jop_key仍明确拒绝未实现的EL0密钥生命周期，不能用返回空值冒充密钥切换。
下一段应补齐共享缓存用户指针签名及EL0/EL1、任务切换的密钥保存与恢复。
参考Snapintosh/compat/pauth-switch.S的完整保存/恢复边界，但其EL2/HCR路径不适用于sheng EL1。
GDB采集器同时修正了旧39位内核指针下界，允许读取实际47位内核保存帧。

运行时进一步命中shared_region_pager_match：按对应dSYM给出的结构偏移读取，
si_ptrauth=1，实际jop_key参数x3=0。与先前普通滑页si_ptrauth=0的记录分开保存，
不把普通映射的零参数当作认证映射证据。认证pager现场保存在
private/experiments/20261024-native-arm64e/virtio-storage/auth-pager-40088447141。
这确认原认证缓存页进入了零JOP标识路径，现有EL0 PAC接入仍不完整。

### 原生EL0密钥接入开始实施

补丁pac/0003保留既有EL1补丁，新增每CPU的内核IA/IB/DA/DB/GA保存区。
EL0异常入口先用原始CpuDatap恢复全部内核密钥，再认证UPCB和保存帧；
返回所选用户线程的最后边界才根据其JOP/ROP标识安装用户密钥，
内核任务切换期间保持内核密钥。A/GA按JOP域推导，B按ROP域推导，
各128位密钥由内核GA下四个不同标签的PACGA结果组成。GA最后安装。

ml_enable_user_jop_key与disable实现成屏蔽中断的临时A密钥窗口，
保留C返回依赖的IB及内核GA，供原有pmap_sign_user_ptr执行真实签名；
默认JOP标识改为非零1，避免原认证页绕过签名。普通ARM64任务使用独立标识。
对照Snapintosh的保存/恢复约束，但没有使用其EL2/HCR调用。

ARM64E汇编语法检查及补丁准备通过，CI40095627621正在构建。
尚未证明launchd已运行，硬件验收保持false。
本阶段使用cpus=1；多核、休眠恢复、内核初始密钥熵及密钥存储保护尚未验收。
新增诊断只从配对DWARF读取四个计数，不导出密钥材料。

### 原版ARM64E launchd主函数首次执行通过

CI40095627621构建通过，内核UUID9C3F92D9-2AC7-3932-82F7-757ACDB856FF，
组件候选SHA256 334dee70e8e838c080ecd2d5d74211c647588fef1483509b1261f5711c4ef063。
QEMU在实际启动栈取得launchd Mach header=0x104e50000，配套LC_MAIN偏移95360，
真实主函数0x104e67480命中。首条PACIBSP执行后PC=0x104e67484、PSTATE=0x60000000。
缺页处理后的16字节7f2303d5ff4305d1fc6f11a9f65712a9与配套原版launchd相同。

对应DWARF解析的每CPU计数为：kernel_entries=1191、user_returns=1192、
completed_signing_windows=37428、signing_active=0，符合暂停在EL0时的一次未返回内核。
块读取失败0，未见此前libdyld虚表认证错误。实际机器指令也确认pmap临时窗口内
仅执行PACIA/PACDA与直接调用，不在用户A密钥安装期间认证内核指针或进行间接C调用。

这确认QEMU进入原版launchd主函数，不等于launchd已稳定工作或桌面已启动。
证据保存在private/experiments/20261024-native-arm64e/user-pac/launchd-main-40095627621。
下一次观察继续原执行流，并将系统调用采集延后到launchd首条指令完成，
避免前面的dyld调用耗尽512条预算；仍使用同一120秒期限。

### launchd已开始恢复系统启动任务

同一候选从实际LC_MAIN继续原执行流，保留原始120秒期限。
原版launchd输出hello, launchd、Darwin Bootstrapper Version 7.0.0、
BaseSystem environment starting，创建system域并执行mount-phase-1。
真实mount[2]及apfs_boot_util[2]执行到内核shared-region路径，随后原版
apfs_boot_util在等待磁盘中不存在的iSC/APFS角色卷：
get_apfs_node role5 on 69646961-6700-11AA-AA11-00306543ECAC、
mount_by_role role256 on iSC。没有对磁盘分区进行写入或伪造这些卷。

采集466次主函数执行后的选定真实系统调用，预算未耗尽，
120秒截止时无panic正文，signing_active=0、kernel_entries=user_returns=6584、
completed_signing_windows=207524。这证明launchd已开展启动任务及实际子程序执行，
不代表恢复系统启动流程完成、UI可用或sheng实机通过。
证据保存在private/experiments/20261024-native-arm64e/user-pac/launchd-running-40095627621。

补丁pac/0004补齐违规或嵌套签名窗口的失败出口：先恢复内核A密钥，再进入panic。
CI40096344826构建通过，修正版已完成相同启动观测。

后续磁盘布局参考已核对：Snapintosh/probes/bootmedia.py给原始恢复根卷与
独立ISC镜像分别提供真实GPT分区，FULL-INSTALL.md说明ISC含xART及系统容器角色卷。
当前磁盘仅含BaseSystem，不能把等待这些卷误判成launchd或PAC仍未启动。
Snapintosh/tools/make-isc-fixture.py的输入契约是新格式化的空APFS测试镜像，
不使用宿主私有xART内容，也不能称为SEP可信存储。下一阶段应先构造隔离的QEMU测试磁盘，
再验证原版apfs_boot_util，当前不改sheng分区。

### 上一轮候选与复测结果

CI40096344826，内核UUID84D29D6C-AC14-38FA-BAF1-B9B0699BAC7E，
候选SHA256 d8f7d6a47161482aeec76131bb0b4e0d5df14150f19e227a72982e3a7b7fd35b。
QEMU再次进入原版launchd，43.730秒完成首条主函数指令，随后正常启动mount/apfs_boot_util，
观测到120秒截止，无panic、磁盘读取失败0，466次选定系统调用，采集预算未耗尽。
每CPU诊断kernel_entries=user_returns=6567、completed_signing_windows=207524、
signing_active=0。违规窗口出口经过编译及正常路径复测，未注入违规调用。

实际启动证据保存在private/experiments/20261024-native-arm64e/user-pac/launchd-running-40096344826。
该轮实验内核现已被替代并删除；原始内核、dSYM及map保留于
private/ci/macos26-arm64e-kernel-40096344826。已替代的实验内核与一次性ESP副本删除，
输入恢复卷、配套组件、现用实机恢复备份和全部诊断记录保留。
本轮未部署sheng，hardware_admitted与loadable继续为false。

### iSC挂载任务已通过

独立工作流40099729442生成新的2 GiB空APFS容器及GPT测试盘，含xART=0x100、
Preboot=0x10、Hardware=0x140。参考Snapintosh的空卷角色字段与校验和处理，
只修改本次原生格式化产生的、UUID及空状态均匹配的卷。没有拷贝宿主xART内容，
也没有实现SEP可信存储。宿主格式化工具版本及全部卷UUID保存在isc.json。

第一轮保持两块盘只读。原版apfs_boot_util已找到/dev/disk2s1，
但挂载/System/Volumes/xarts返回EACCES，随后launchd报告mount-phase-1失败并请求panic。
配套IOStorageFamily源码IOMediaBSDClient.cpp中，只读介质收到FWRITE时返回EACCES。
该轮证据保存在private/experiments/20261024-native-arm64e/isc/readonly-40099729442。

0019和0021为NativeVirtioBlock增加显式启用的测试介质写入与实际flush，
默认仍要求只读后端。只有原生构建宏和指定设备树属性同时存在，才能协商可写设备。
0020将第二块盘的全部写入限定到新建qcow2层；底层ISC及原BaseSystem在QEMU中均以只读打开。
独立QEMU工具的写入、读回、flush对照通过，底图哈希保持不变。

CI40100580890构建通过，内核UUID89887759-CAB1-300F-96D6-C05A97ADD2E1，
候选SHA256 e75fbe390d20abe7c985b88525b9f805b94dfc6e74b71ae786c0cf1796d070e6。
当前候选保留于out/macos26-scratch-40100580890，配套原始内核与符号保留于
private/ci/macos26-arm64e-kernel-40100580890。
实际QEMU启动再次执行配套原版ARM64E launchd，三个卷分别出现mount-complete：
SHENG-xART、SHENG-Preboot、SHENG-Hardware。launchd在客体时间49.290秒进入
data-protection，180秒期限内没有后续任务或panic正文。此时仍不能认为恢复系统启动完成。

采集469次选定系统调用，预算未耗尽；块读取失败0，PAC计数为
kernel_entries=user_returns=6522、completed_signing_windows=208161、signing_active=0。
本轮实际块写入及flush计数均为0，因此只确认介质权限接入及原版APFS挂载通过，
尚未用客体实际I/O验收新增写入与flush请求路径。两块原始输入在运行后重新核对哈希，均未改变。

后续只读现场已确认这里并非正常等待，见下节；没有panic正文不能排除异常循环。
当前日志包含failed to find AppleKeyStore service，但尚不能只凭这行确定任务内部的停止原因。
完整日志、截图、首次异常记录、配套符号身份和采集报告保存在
private/experiments/20261024-native-arm64e/isc/overlay-40100580890。
已删除本轮一次性ESP、写入层及被替代的旧实验内核，保留当前候选、原始配套输入与诊断记录。
本轮未部署sheng；实机的最新验证点仍为旧版Image4检查，硬件准入保持false。

### data-protection停止原因已定位到诊断地址宏

编译器DWARF与实际proc_name_address指令给出47位进程和线程布局。
只读快照中PID1仍为launchd，PID3也为尚未完成exec的launchd子进程。
原版Boot配置将data-protection指向init_data_protection，后者链接seputil，
但当前没有证据证明该子程序已执行，不能将停止原因归于SEP等待。

最终PC位于sheng_mmu_sync_fault。将断点延迟到load_init_program后，
捕获首次进入：ELR=0xfffffe00075c7178、ESR=0x96000046、FAR=0x16d4dfd90。
实际故障指令为_bcopyout中的stp x3,x4,[x1]，目标是用户栈。
这是本应由正常缺页路径处理的访问，此时sheng_bootstrap_capture_enabled实际已为0。

实际Mach-O反汇编显示，SHENG_EARLY_ADDRESS的分号被Darwin汇编器解释为注释，
ADRP之后的ADD被删除。开关读取了所在页的起始字，而非开关本身；
故障出口又按错误记录地址恢复TTBR0及跳转地址，引起后续异常循环。
同一个宏还影响早期记录和framebuffer映射地址。

0c6ea1b改为逐行汇编宏，修复三个头文件的全部调用。
回归测试拒绝旧版Mach-O对象，修正版含12对PAGE21/PAGEOFF12及完整ADRP/ADD指令。
QEMU独立异常用例通过：复制向量、MMU切换、无有效栈异常捕获、
诊断关闭后的原分发、framebuffer映射冲突拒绝。
CI40105000086完整内核已构建通过，后续运行结果见下节。

观察工具新增按配套符号身份校验的allproc及线程快照，读取有数量和地址范围限制。
保留的用户寄存器只表示最近EL0边界，保存的内核帧来自调度上下文，
均不能单独当作正在执行的故障位置；本次归因依据是延迟断点取得的首次异常寄存器。
现场保存在private/experiments/20261025-native-arm64e/data-protection，
回归对照保存在同日期的bootstrap-address目录。一次性ESP及写入层已删除。

### 原版data-protection已通过，下一项为sh的任务PAC策略

CI40105000086的完整候选UUID86F62D91-75A9-3AD5-8342-AC6CC3439B2E，
SHA256 88648f9c0c1135571d6e214603bc4d039e91eb72b01fa51bf38f1778b087bdbf。
完整保留此前11个原版组件。首轮封装漏带FSCompression，导致压缩launchd读取返回errno45；
该轮已淘汰。启动工具现对配套BaseSystem的pthread、APFS及FSCompression进行运行前检查。

修正版实际执行原版seputil，输出init_data_protection: No SEP present on this device后返回。
launchd继续执行detect-installed-roots、select-boot-mode、commit-boot-mode、
auto-pivot-root及allow-non-platform-code，说明此前data-protection阻断已解除。
没有加入SEP或AppleKeyStore替代服务。

新的真实panic为userspace panic: boot task failure: restore-datapartition - exited due to SIGKILL。
此任务通过rc_script_wrapper执行sh。延迟断点在handle_pac_fail捕获到
ESR=0x72000000、指令BLRAAZ x8，目标为缓存dyld的lldb_image_notifier，且指针未签名。
原版dyld源码prepareInCacheDyldAllImageInfos与实际指令序列一致。

匹配DWARF的只读现场确认sh的task.disable_user_jop=1、线程machine_flags=0x3，
而SCTLR_EL1=0xfc54793d仍开启IA/DA。父rc_script_wrapper和launchd的disable_user_jop均为0。
原版mach_loader.c将com.apple.sh列入可加载插件的keys-off例外；
原生EL1密钥边界实现此前只切换密钥，没有执行该任务策略。

独立补丁pac/0005在最后EL0返回边界按原版线程标志设置SCTLR的IA/DA开关，
B密钥保持开启；从EL0进入内核时，在任何内核认证前恢复IA/DA。
这是EL1边界实现，未照搬Snapintosh的EL2根切换处理。
847a791已提交，CI40106907035构建及运行验证通过，见下节。

完整启动现场保存在private/experiments/20261025-native-arm64e/bootstrap-address/full-40105000086，
首次PAC异常及任务策略保存在同日期shell-pac目录。两个原始磁盘仍以只读底图打开，
一次性写入层已删除，已替代的CI40100580890实验候选也已删除，原始内核及配套符号保留。
512条系统调用预算已耗尽，但后续原版控制台和panic完整保存；不能把计数截止当成任务不再运行。

### sh及bash已执行恢复脚本，原版tmpfs已加载

CI40106907035的内核UUID0387A9C5-C7CD-330D-9867-E4BF1A40B09E。
原版sh成功转入bash，输出rc.temporaryDataVolume -- Arguments:[]，随后实际执行
bs-data-tasks -P 1、umount及mount_tmpfs。此前BLRAAZ的PAC失败没有再次出现。
内核停止处SCTLR仍开启IA/DA，PAC计数kernel_entries=user_returns=17390、
completed_signing_windows=288839、signing_active=0。此处只证明已通过这段脚本执行路径。

首次脚本运行因com.apple.filesystems.tmpfs未封装而返回exit(71)。
增加原版tmpfs及其依赖后，候选SHA256为
781d96fb7e9acc8e1873fbea91a01d8a7e72a8dd56cae064892ab8e01588c57e。
内核已注册该模块，但原版kmutil的LoadFromKC请求被拒绝：
Access Failure - client not entitled to manage kext in non-primary KC。

源码确认：本次外层是旧式MH_EXECUTE预链接容器，因此KLDBootstrap传入KCKindUnknown；
原版组件则保留MH_DYLIB_IN_CACHE文件集标记。kmutil只允许管理BootKC，
因组件带文件集标记且类型不是Primary而被拒绝。这不是tmpfs挂载函数的运行结果。

0049与封装器增加配套版本标记及_NativePrelinkPrimary元数据。
只让本次已预链接、类型为Unknown且带该标记的启动组件通过原BootKC范围检查；
根权限、任务entitlement检查、其他KC限制和原版模块代码继续保留。
c87c97a对应的CI40108221784构建通过，内核UUID68F2CBDB-9E98-3785-A2E1-9613AF4762B6。
完整恢复候选SHA256 a6155d0701e8479e41dd7352b39e2b78ed9a65d43f70c2a6ba6ad25aa59d4fab。
QEMU实际接受原版kmutil的LoadFromKC请求，原版tmpfs完成module start并加载成功。
容器仍为旧式预链接，日志中的?? KC不能解释为真正MH_FILESET已构造。

新的阻断是原版mount_tmpfs挂载返回EINVAL。断点0xfffffe000d5e54dc取得实际参数：
容量0x4000页、每页16KiB、节点上限1000000、hw.memsize=512MiB。
原版模块的后续校验要求节点数乘288字节不超过内存预算，当前预算约76.8MiB，
而默认一百万节点需要约274.7MiB。容量已经从2.5GiB自动缩到256MiB，
因此不能只依据容量提示判断失败原因，也不是此前假设的用户页大小不一致。
观察器增加实际QEMU RAM与真实连续内核分配参数，下一轮用4GiB RAM、3GiB内核窗口，
保留原版脚本和组件复测。DarwinBoot实际分配owned=0xC0000000，hw.memsize随之增加。
原版mount_tmpfs成功创建Data，ditto复制模板，mkdir及setlanguage完成，32MiB的/Volumes也成功挂载。
这轮没有修改原版工具、脚本或tmpfs校验；之前的EINVAL由实际内存配置触发。
新的停止为prebootensurer exit(70)：Unable to find IODeviceTree:/chosen boot-uuid。
正在按Snapintosh的恢复根卷身份机制，发布已验证的BaseSystem卷UUID及apfs-preboot-uuid。
不会把BaseSystem卷伪称为已安装系统的VolumeGroup；安装根卷需要独立的组身份和Preboot内容。

只读断点现场及完整启动日志保存在private/experiments/20261025-native-arm64e/tmpfs。
新增GDB读取停止时128/512字节内核栈的选项，避免只见参数寄存器而无法读取校验栈。
首轮错误使用仅支持x0-x7的入口选项读取SP，工具拒绝，寄存器保留在partial_report；
第二轮独立栈读取成功，已删除两轮一次性写入层和旧CI40106907035实验候选。

config/macos26-recovery-modules.json固定配套恢复系统所需的pthread、APFS、
FSCompression和tmpfs，封装器使用--recovery-components，自动带入原版依赖。
旧内核缺少启动容器身份契约时，完整恢复配置会在生成镜像前拒绝。
观察器现会在完整panic输出后的halt_all_cpus处收集现场，避免继续等满观察期限；
实际stopped_at_halt=true已确认，reached只表示请求的检查点，不代表系统完成启动。
上述两轮证据位于private/experiments/20261025-native-arm64e/user-a-policy。

### 恢复系统开始启动服务，重启来源继续取证

本轮保持同一候选，只补齐实际BaseSystem卷的boot-uuid/apfs-preboot-uuid。
原版prebootensurer找到该身份后，因没有Recovery角色卷而正常返回；
这不代表已经具备完整Recovery容器或Preboot启动对象。
原版脚本继续bs-data-tasks -P 2，随后执行sandbox-enable-root-translation、rc.cdrom、
init-with-data-volume及fips等任务。用户态corecrypto FIPS POST全部通过。
launchd开始运行系统域服务，已见recoveryosd、InstallerProgress、configd及fseventsd的生命周期。
尚未验证图形界面；随后用户空间发起完整关机/重启流程，停止处没有最终panic头。

该轮打印566017字节，单次RAM快照只保留前缀和尾部，484097字节中段已覆盖。
不能据此归因重启，也不能把first-sync记录中的普通缺页当作致命异常。
观察器增加--stream-retained-log，每秒通过GDB中断复制实际环形缓冲，随后继续执行。
最多256次采样，按UUID验证，按单调字节计数去重，覆盖缺口和guest writer丢字节分别记录。
它会扰动执行时序，只用于QEMU，不是实机日志传输。
环形缓冲多次回绕、采样缺口、未提交写入、UUID不匹配及计数倒退的针对性测试通过。
实测173次采样，保存602807字节，missing_bytes=0，guest_dropped_bytes=82，因此complete=false。
已确认原版recoveryosd运行pmset autorestart 1失败，随后执行/sbin/reboot。
原版recoveryosd的0x1000015fc–0x100001614在子任务非零退出时调用重启函数，与日志吻合。
这是原版用户空间策略触发的重启，不能称为内核panic，也不能称为恢复界面可用。
同轮大量launchd查询返回Sandbox restriction，原版Sandbox尚未封装；下一轮加入配套原版组件对照。
身份版与stream版现场保存在private/experiments/20261025-native-arm64e/recovery-services，
一次性ESP和写入层已删除。

sheng准入还需独立解决根盘路径、配套内核硬件初始化和可读日志回收。
VirtIO根盘的QEMU通过不能代替平板UFS；首轮也可评估只读内存盘路径。
硬件封装器目前仍只准入先前记录的Image4早期实验，未对新版用户空间候选放行。

### 原版Seatbelt策略接入，继续补齐服务启动依赖

同内核加入原版com.apple.security.sandbox及依赖AppleEffaceableStorage，
候选SHA256 e516d193b67626cf269d33f515bc8a85f456b1b58f8e42758345a55672d49272。
实际加载Seatbelt sandbox policy，先前全局Sandbox restriction查询拒绝没有再出现。
180秒观察期没有再次进入关机流程，也没有最终panic头，但仍有多个服务退出，不能称为稳定恢复系统。
PAC计数kernel_entries=user_returns=366516、completed_signing_windows=558160。

cfprefsd多次exit(254)。原版25F71二进制在0x100000604调用_qtn_proc_apply_to_self，
非零返回经0x10000065c保存后原样传给_exit；该故障路径会记录Failure to configure quarantine。
当前容器没有原版Quarantine策略。下一轮加入配套com.apple.security.quarantine作运行对照，
不把系统偏好服务退出直接归因于平台UUID；后者另用只读函数入口/返回观察验证。
恢复组件清单已加入通过加载验证的原版Sandbox，Quarantine尚未纳入固定清单。

### 原版Quarantine解除偏好服务早退，开始建立Aqua会话

增加原版com.apple.security.quarantine后，候选含15个原版模块，
SHA256 3f7eefaf752a8a5f26c5ba5755b4c8a3d4dd4aff666e86001e84a8ba22bf50e7。
实际注册Quarantine policy及其Guarded vnode策略；cfprefsd此前exit(254)不再重复出现。
原版pmset autorestart 1返回成功，recoveryosd越过该检查，没有再执行此前的重启分支。
mountrecursive返回255后，原版仍继续Establishing an Aqua Session，创建审计会话100001。
WindowServer被启动但反复exit(1)，尚未定位到具体原因，不能把进程创建解释为图形界面可用。
logd和opendirectoryd也尚未稳定可用，仍有No such process查询失败。
180秒观察到用户空间继续运行，没有最终panic头或同类重启；不表示长期稳定。
全程保存292903字节，missing_bytes=0、guest_dropped_bytes=82。
Quarantine已纳入固定恢复组件清单，没有修改原版守护进程或把pmset返回值强制改为成功。

独立只读平台UUID对照：IOBSDGetPlatformUUID实际返回0x31（超时），
gIOPlatformUUIDAndSerialDone=0，返回缓冲为全零。
生成的QEMU树没有提供平台身份。仅增加/options/platform-uuid的运行正对照仍返回0x31，
gIOPlatformUUIDAndSerialDone仍为0。这证伪了仅补设备树属性就够用的判断。
源码中/options回退仅在x86分支；原版ARM64路径需要Apple的unique-chip-id/chip-id。
0050给SHENG的ARM64增加显式platform-uuid回退，保留现有芯片身份优先路径，
沿用XNU已有的OSString、平台属性及资源发布流程，不直接改gethostuuid返回值。
观察器增加显式--qemu-platform-uuid，仅允许QEMU开发根卷，默认保持未设置。
同一恢复候选的VM身份对照也已运行180秒，没有最终panic头；WindowServer仍有exit(1)，
不能宣称该参数修复了所有服务。0050修复后的函数返回值尚待新内核验证。
设备树检查覆盖卷UUID字符串和平台UUID二进制的不同ABI，冲突及缺少options时拒绝改写，
并保证此合成身份不能通过默认路径进入硬件树。


### 平台UUID已读回，CHRP代理保留身份

CI40111511884构建0050，内核UUID5F1E31A9-98DD-33C6-8E3D-191D83FDCBF7。
15个原版组件候选SHA256为565d7418bcefee163b2916e62cb37ec8776b0b5d82612850e5087d84ac8c7ccd。
仅写/options的新版内核对照仍返回0x31；不是0050未编译。
IODTNVRAM::init会用空字典替换/options属性表，直接注入的属性在查询前已经被清除。
改在本工具新建的易失CHRP代理common分区写入platform-uuid，按原版编码转义零字节和FF，
更新Adler校验。拒绝覆盖已有变量或不同身份，默认硬件路径不注入合成VM身份。

只读函数入口/真实返回对照已确认：IOBSDGetPlatformUUID返回0，调用栈匹配，
返回16字节与显式VM UUID 7e8b064b-8ddb-54c4-b332-6fe0c34f937c完全一致，
gIOPlatformUUIDAndSerialDone=1。该身份只属于自建VM，不是Apple设备身份。
同版180秒启动记录173次采样，101498字节，missing_bytes=0、guest_dropped_bytes=0、complete=true。
原版recoveryosd继续建立Aqua会话；停止快照中opendirectoryd和cfprefsd仍存在。
没有最终panic或完整关机流程，但截图仍只有文本面板，WindowServer的退出原因继续单独取证。
普通logd被launchd以158排除，原文为Service cannot be loaded on current os variant；
恢复系统有recoverylogd定义，因此不把普通logd缺失解释为服务崩溃，也不强行启动错误类型服务。

上述正负对照、连续控制台和匹配布局保存在recovery-services/uuid-native-*目录。
下一次sheng实验仍需配套26.5 UFS根盘读取路径、硬件初始化及可回收日志；
不能用QEMU的VirtIO根盘替代UFS，也不能只因VM平台身份通过就放开硬件准入。


### sheng UFS配套构建入口

增加显式--build-ufs-driver，使用固定UniXNU NativeUfs源码及25F71配套IOStorageFamily头，
构建独立ARM64E传输组件。它与QEMU VirtIO组件分别输出，不自动替换根盘。
CI通过native_ufs=true启用，默认关闭；组件仍保留原版boot-arg硬件开关和只读根盘行为。
当前只建立编译入口，尚未确认构建、原版存储ABI链接或实机运行；硬件准入继续关闭。

UFS参考路径的生产解析器固定读取LUN0名为userdata的GPT分区，并要求首块为SHNGROOT清单。
因此即使组件编译通过，也不能原样启用在现有Android数据分区上。
后续需要单独的根盘区域及严格匹配的布局入口；本轮没有重分区、刷写或改动Android数据。


### WindowServer主动退出定位到HID及显示初始化

只读断点捕获原版WindowServer(pid 92)调用exit1，原始等待状态0x100，即exit(1)。
使用匹配DWARF的thread_ro/proc_ro/task归属，取得原始74字ARM64E保存状态和实际共享缓存slide。
用户调用栈为libsystem_kernel ___exit、libsystem_c、SkyLight _WSInitialize、_SLXServer。
原版25F71缓存内的实际返回点0x186dc2ee4前一条调用是exit(1)，同一错误出口记录
Cannot open the HID and display/cursor system.。这把图形失败定位到HID及显示初始化，
不是本次内核panic；具体是哪个前置IOKit查询失败仍需单独验证，不能仅由共同出口推定。

观察器增加独立0026补丁：支持47位原生内核的进程选择，校验匹配内核哈希及双向归属，
PAC元数据仅为只读地址查找移除，记录原始值，不宣称认证。保存状态计数必须显式选74；
此前默认72的读取未取得用户栈，其局限和失败工具现场均已保留。
3项定向测试及真实WindowServer退出捕获通过；完整现场在recovery-services/windowserver-state-40111511884。

UFS构建40113551826已进入实际编译。第一处错误是未开启旧VerifiedBlock功能时，
读计时代码仍引用被条件编译隐藏的timerTicks和native_ufs_read_ticks；不是macOS存储类接口错误。
内核和VirtIO已构建，UFS尚未生成可用组件，后续单独修复该条件边界。


UFS独立0027补丁把传输读计时移出可选VerifiedBlock条件，不改校验策略。
独立0028允许编译期限定根盘分区；本项目UFS组件明确只匹配macosroot，不回退userdata。
使用真实RootLayout生产解析器运行两组ASan/UBSan测试：上游userdata路径及专用macosroot路径，
原有GPT/清单错误和2048次变异检查均通过；只有userdata时专用版在读清单前拒绝。
它证明解析范围受限，不代表设备已有该分区、UFS硬件可用或根盘内容已准备。


### UFS配套构建、重定位与默认关闭路径通过

CI40114236144成功，基核UUID F149677D-1FE8-3697-ABB0-3820611A9535。
UFS独立组件使用原版25F71 IOStorageFamily，块设备326个虚函数槽及23个重载通过名称和PAC契约检查，
389项导入全部解析，702个认证指针保留元数据后交给XNU原生签名器。
含15个原版组件的候选SHA256为20b9343e00d0d8c46d572111e4f6a25e975f4d020ebfeb7a08426ade4ebc163b。
QEMU到达IOFindBSDRoot；另一次断点实测NativeUfs::start真实返回false，调用栈匹配，
matched=1、probe_requested=mapped=root_step=blocks_published=0。
这验证组件可经IOKit调用且默认关闭，不代表QEMU执行了真实UFS读盘或sheng硬件已通过。

独立macosroot镜像1579155456字节，清单后1MiB处放置原始BaseSystem完整磁盘，
复制时校验字节数及已配套SHA256，源盘没有修改。生产RootLayout解析器读取其真实清单通过，
并运行GPT错误、清单边界和2048次变异检查。普通清单哈希不是签名或原版sealed root认证。
原版APFS认证仍由原有root-hash及原版挂载路径负责；尚未在UFS上执行挂载。

历史GPT备份只读核对：LUN0(sda)没有未分配区，userdata占满其余空间。
LUN4(sde)在macoslog创建前总空闲约284.6MiB，也放不下该根盘。
因此macosroot目前只是镜像目标名，设备上没有该分区。
保留Android时需要另行解决实际存储空间，不能把编译期分区名当成已完成的分区创建。
历史布局和CRC验证结果保存在private/experiments/20261025-native-arm64e/ufs/saved-gpt-layout.json；
它不是当前在线分区表。上述实验均未连接设备或写入分区。


### 64 GiB根分区已部署，Android数据重建完成

用户明确允许丢弃userdata，并选择64 GiB给macOS、剩余给Android。
root Recovery核对LUN0真实4 KiB逻辑块、原GPT及未挂载状态后，
仅缩小sda29的结束位置并新增sda30/macOS根盘条目；其余GPT条目、磁盘身份保持不变。
macosroot实际名称为macosroot，GUID 66ac0996-e1bb-4e93-8ffe-c90ed97a61ff，
LBA47229696..64006911，68719476736字节。
userdata保留原起点、类型、GUID及属性，结束于LBA47229695，180777385984字节。
先更新备用GPT，再更新主GPT，每次写入及最终两个1 MiB窗口均读回一致。
当前恢复材料在private/backups/20261025-macosroot-64g，不包含已丢弃的userdata内容。

原Recovery执行wipe_data，日志确认按缩小后的容量丢弃userdata、重建metadata。
Android vold随后重新创建加密F2FS；sys.boot_completed=1，槽_a，/data挂载正常，
macosroot仍指向sda30。boot、系统、Recovery、UEFI及64 MiB macoslog保持原内容。
现场在private/device/macosroot-write-20261025/android-fresh-data.txt。

根盘只写入一次，首次ADB exec-in未提供可靠远端完成确认，后续flush确认超时。
未自动重试；独立读取全部1579155456字节后，SHA256与本地完整镜像一致：
ca20f14cef97cbab92807ebc37afe81af76a4a629a5bf6947a7cb88f517a78c0。
之后flush成功，写入状态依据完整读回标记verified，传输确认局限单独保留。
安装工具改用adb shell -T并等待远端dd fsync退出；未因此重复写盘。

同一40114236144候选又通过sheng物理放置、16K页表及MMU后16格实际像素的QEMU执行检查，
但这不是UFS实机执行。封装时先修复生成ADT中main与恢复卷recoveryos不一致。
进一步核对真实NativeUfs::startRoot发现：上游协调器要求OS与SystemOS两个窗口，
且未启用旧VerifiedBlock时始终拒绝发布。当前单BaseSystem清单不能经过该流程。
此前封装的实验镜像已撤销并删除，没有向设备发送。

独立0030补丁和显式recovery_root构建头增加单恢复卷只读发布：
严格限定一个OS窗口、25F71字节数与已配套摘要，使用实际恢复卷UUID等待原版APFS发布。
SHNGROOT及预期摘要只限定传输布局，不被描述为认证；原版APFS root-hash路径仍负责卷认证。
未启用此恢复模式时保留旧OS/SystemOS与VerifiedBlock规则，二者不能混用。
实际生产协调器的单卷发布、身份拒绝、调度失败回收及启动/媒体失败路径经ASan/UBSan通过，
旧版协调器测试也通过。CI40120489871因设备树补丁归属目录错误而停止，
已修正至UniXNU-sheng目录，CI40120646478正在构建匹配ARM64E组件。
新封装入口会拒绝旧UFS组件、不同内核的观察结果、非零硬件访问计数及错误根分区，
不会把QEMU准入或原版组件注册当作UFS硬件已通过。

CI40120646478构建成功，新UFS组件SHA256为
3368c6884320a2463af595ca5fe3463addde7675ded90bb497a9d1c1ae2b0557。
原版恢复组件及新传输重定位候选SHA256为
76f7302e40972e53613ee0ac32862e07692bff38a7d3516baa5e2e02b37779c2，
基核UUID A9A489DF-8ED4-3534-997A-C047F765BA5A。
同版通过物理入口/MMU后写屏以及IOFindBSDRoot观察，原版组件注册及source crypto初始化通过。
第一次观察器在OSKext摘要bzero的写页异常入口暂停；这是向量断点现场，不等于panic。
后续允许原版异常处理继续执行，实际到达IOFindBSDRoot，未修改内核规避该页异常。

独立调用观察中NativeUfs::start真实返回false，返回栈匹配，matched=1，
probe_requested=mapped=root_step=blocks_published=0。
150663168字节实机实验容器已封装，SHA256为
305ea914ea6ac33ae98720668ea1b2c83f0724f2d232fef27c10dea39d406d67。
它只经fastboot临时启动，要求3 GiB自有内存窗口；硬件是否能分配该窗口仍待设备验证。
显式启用native-ufs-root=1及诊断，根分区只读，不传QEMU-only启动参数或合成VM身份。
实机UFS读取、原版APFS挂载、launchd及RAM日志恢复仍没有通过记录。
当前可开始这一轮sheng实验，需现场按键和视频配合。
现场和匹配资格记录在private/experiments/20261025-native-arm64e/ufs-recovery。

### 25F71实机已进入UFS根卷发布等待

40120646478候选临时启动收到Booting OKAY；用户照片显示
SHENG - FIRST PANIC及UFS ROOT FAILURE: root window volume，正在等待
808EAC5E-8275-478D-814C-2229D8EB8D07。
按该诊断唯一源码路径，控制器初始化、LUN0 GPT/根盘清单读取、配套单OS窗口身份检查、
NativeUfsBlock配置及服务发布已经走过，30秒后仍未找到具有预期UUID及父链的APFS媒体。
这不证明全部BaseSystem内容读取正确或APFS已挂载，详细读取计数尚未取得。

仅恢复日志的临时UEFI容器随后尝试NativeLogSave，再拒绝不可执行标记并返回菜单，
没有运行下一份内核、重设RAM请求或改写系统分区。用户多次选择恢复入口。
原Recovery对macoslog只读导出，只有先前OBSERVED.JSON，没有NEXTLOG.BIN或CAP目录；
因此本轮未取得完整RAM日志，不能把屏幕照片当成日志分区写入成功。
a槽仍可启动，macosroot仍为64 GiB，Android sys.boot_completed=1。
本轮照片、传输及只读导出记录保存在private/device/ufs-recovery-40120646478。
已使用完毕的日志恢复部署镜像已销毁，元数据及诊断保留。

下一版0031只在恢复模式为NativeUfsBlock这个磁盘映像子设备声明Virtual Interface/External，
不把底层UFS控制器描述成VirtIO。前序QEMU中原版APFS nx_is_virtual曾读取同一属性，
漏报时进入真实系统盘的命名快照分支；这是本轮APFS等待失败的待验证解释。
0032把媒体列表及prepared/published/read/failure计数放在panic前部。
0051及渲染器把面板高度按屏幕计算为6..24行，映射覆盖对应像素区，
panic文本保留上限从511扩至4095字节；满屏后固定首段，后续回溯只使用末两行。
实际AArch64 QEMU渲染24行，逐像素确认80行后续日志不覆盖首段，
RAM中保留511字节以后的消息尾标记，真实字体画面已检查。
该布局及子盘属性尚未部署sheng，不能称作APFS修复已通过。


### 3 GiB原生窗口的日志恢复修正已封装

0033保留旧RAM范围，增加实机UEFI RAM表中的0x8c0000000..0xa00000000，
仍拒绝0x8bb300000..0x8c0000000间隔。旧日志范围容不下3 GiB窗口，
此前请求可能在校验时被拒；上一轮未记录MACOSLOG状态，不能据此确定唯一故障。
只有指定macoslog分区的GPT、类型、名称和块尺寸全部匹配后才尝试连接FAT驱动。
ARM.BIN/RECOVERY.BIN独立保留最新EFI结果；它们不等于完整RAM捕获。
宿主实际保存器已通过高地址请求、跨3 GiB的panic页、分区绑定、失败状态读回和原有拒绝测试。

CI40124513764成功，配套内核UUID C4507D38-AF83-365C-B045-371D1BA97590，
SHA256 002f044bfc67088b1f27278386843203032a79a72db7973463d405296395ec92。
实际326槽/23个override及PAC ABI匹配，UFS默认关闭时返回false且硬件计数为零，
匹配物理放置的启动汇编进入arm_init并完成16个标记。
新加载器在QEMU进入IOFindBSDRoot，原组件注册及sourcecrypto初始化通过，24行面板就绪。
这些结果不证明实机UFS或APFS挂载通过。

正常sheng固件已重新编译并包含0033，新实验镜像位于
out/macos26-ufs-logfix-hardware-40124513764，资格记录位于
private/experiments/20261025-native-arm64e/ufs-logfix。
上一份40120646478部署镜像和配套ADT已销毁，诊断、符号和恢复输入保留。
下一轮验证NEXTLOG请求建立、实机首次panic详情及重启后的捕获文件。
尚未部署本候选，跨重启RAM捕获仍未验收，Android仍处于可启动状态。


### 本轮恢复包与面板资格纠正

40124513764实机照片仍显示根卷等待，未显示新增计数。
查构建记录确认0051未加入build_macos26_xnu.py的显式PATCHES，原24行资格只检查
sheng_console_rows的计算值，没有核对arm_init实际传给绑定函数的行数。此前“大面板已在此内核通过”的结论撤回。
独立渲染器的24行/防覆盖结果保留。现加入0051、记录实际sheng_panel_bound_rows，封装同时要求
编译补丁SHA与真实绑定24行；6行绑定即使计算值为24也拒绝。定向4项封装测试通过，Linux准备阶段实际应用0051通过。

首次恢复包显示no boot entry found。Config.c表明这是配置卷未读取，而非ParseKernel拒绝标记。
20 MiB强制FAT32仅40298簇，EnhancedFatDxe明确拒绝低于FAT16上限的FAT32；已改FAT16，实际40609簇。
失败部署镜像已销毁，FAT16包已临时启动等待读取结果。尚无自动RAM捕获成功证据。


### FAT16恢复入口未确认执行，设备已恢复Android

FAT16容器发送和boot命令均返回OKAY，但用户报告仍在FASTBOOT，不能判定NativeLogSave已运行。
原Recovery只读导出macoslog仍只有OBSERVED.JSON；没有NEXTLOG、ARM.BIN、RECOVERY.BIN或CAP目录。
因此既不能宣称日志修复实机通过，也不能仅凭空目录判定RAM已丢失。
logfs、xbl_sc_logs和rawdump有界只读快照已保存；日志中对应download/boot及EBS存在，
没有可以证明自构建UEFI保存器执行的记录。FAT16失败部署镜像已销毁，元数据保留。
设备已正常恢复Android，确认sheng、_a、sys.boot_completed=1，未改槽或刷写系统/Recovery。
全部现场保存在private/device/ufs-logfix-40124513764。

0051构建修正的CI40161755752成功，后续重新验证实际绑定行数，不沿用旧面板资格。


### 实际24行绑定与手动恢复菜单已通过QEMU

CI40161755752产物核对0051及日志头SHA后重链接，UUID 6F504502-D6FD-3E1A-85DA-CCCD70637FA7，
候选SHA256 5a8a473d5603fe9004535b4cafdd19f3c2883ab087438a6e339d20d1988f611a。
QEMU进入IOFindBSDRoot，actual sheng_panel_bound_rows=0x18，原组件接口及sourcecrypto初始化通过；
匹配sheng物理放置的启动汇编通过，UFS默认关闭时实际返回false且硬件计数为零。
新硬件实验包位于out/macos26-ufs-panel-hardware-40161755752，尚未部署。
40124513764旧部署镜像及ADT已销毁，日志和配套内核符号保留。

恢复包改为手动选择，避免3秒自动执行在观察前返回或重启。
实际20 MiB FAT16文件在QEMU UEFI下挂载，UniXNU读取unixnu.toml、加载DarwinBoot并显示recover菜单，
确认停留手动选择。硬件恢复入口及macoslog文件系统访问仍未验收。
新的手动恢复包位于out/native-log-recovery-manual-40161755752，不运行新内核或重设RAM请求。


### 分区日志后端缺失已查明，按用户要求优先屏幕启动

手动恢复菜单在实机出现，用户选择后返回菜单；原Recovery再次只读导出仍无状态或捕获文件。
进一步核对sheng.dsc的SHENG_VENDOR_HW=0及最终FD，UFSDxe处于条件关闭分支，未包含物理UFS固件驱动。
FD内DarwinBoot的实际PE含SHNREC01/SHNARM01，Fat驱动也存在，因此不只是补丁元数据未写入固件。
现有UEFI文件保存器缺少访问内部macoslog的物理存储后端；单独修正RAM范围或FAT绑定不能补齐该后端。
用户明确要求优先启动macOS、使用拍屏日志，分区日志后端暂缓，不为此启用整条厂商硬件链。

新24行候选40161755752已临时启动，ABL返回Booting OKAY、a槽状态正常。
菜单标题含6F504502，要求用户先核对版本并记录交接页和stage/prepared/published/reads/failures。
目前等待屏幕结果，不能把传输确认当作该内核已在实机执行。


### 实机连续内核文字通过，根卷识别仍阻断

40161755752 / 6F504502实机视频已保存，确认连续内核文字、NativeUfs: published OS、
APFS v2811.120.14和FSCompression加载。最后等待808EAC5E-8275-478D-814C-2229D8EB8D07，
首次panic摘要为UFS ROOT FAILURE: root window volume；详细计数和媒体列表没有显示。
这证明块服务发布路径已执行，不证明APFS卷已经出现或挂载，也没有launchd启动证据。
设备随后正常恢复Android，a槽可启动，sys.boot_completed=1、ro.boot.slot_suffix=_a。
本轮未刷写分区，视频及恢复记录位于private/device/ufs-panel-40161755752。

源码确认普通日志writer忙时，原panic正文也会被trylock丢弃，只剩独立标题。
对照Snapintosh外部监控器的独立日志状态，sheng没有其EL2服务，改用自身独立首次panic快照与像素区。
0052保持普通24行，下方新增16行panic详情；映射按完整几何扩展，首次文本最多4095字节，
屏幕固定显示容纳的前段，普通环形日志继续保留丢失计数，不伪称整段消息都能同时显示。
AArch64 QEMU实际运行共享头文件，在writer=1、RAM异常头state=3时保留正文，未夺取writer；
逐像素核对真实字体，80行后续普通日志和第二次panic均未覆盖首次详情。
800像素高屏幕的6行普通日志与16行详情几何也通过。结果位于out/native-panic-writer-validation。
本次没有证据把根卷失败归因于UUID、读盘或媒体发布中的某一个；后续依靠可读计数区分。

原手动RAM日志恢复部署镜像已销毁，构建元数据和现场保留，缺失UFS固件后端仍未实现。


### 相同NativeUfsBlock上层链路在QEMU找到根卷

对40161755752候选做独立QEMU对照：GDB绕过物理hostBringUp和GPT解析，从已部署镜像的离线清单
提供RootLayout，替换底层hostRead4k为同一离线镜像读取。实际优化后二进制已核对该私有函数的
参数寄存器，不能按未优化C++声明猜调用约定。ADT禁用VirtIO节点，未让另一个块设备代替UFS子盘。
真正执行NativeUfsBlock、原版IOBlockStorageDriver、GPT及APFS媒体发布和UUID祖先检查。
观察到NativeUfs: OS volume ... ready，BSD root: disk1s1，设备路径明确经过NativeUfs/NativeUfsBlock。
8519次模拟传输读取69771264字节后，到达真实load_init_program入口。
这说明该候选的上层发布及BaseSystem根路径能够工作；不证明物理UFS传输、GPT读取或sheng挂载成功，
也没有观察launchd main。现场及明确的模拟边界位于private/experiments/20261025-native-arm64e/ufs-publication-qemu。

独立panic面的CI40164717613成功，原组件重链接UUID A2FEEAC1-01D7-3D5B-A289-58989E5126A2，
SHA256 f06428a95fc2294f0f66373a57826f971c12d2b1cd91b6943a4c46bd04d099ff。
800x600 QEMU屏幕按实际几何绑定17行普通日志与16行panic，sheng 3048x2032仍为24+16。
封装要求绑定行数等于本次计算值且在6..24内，仍拒绝此前“计算24、实际6”的错误，另要求独立panic面实际绑定16行。


### 独立panic面完整内核验证通过，新实测包就绪

40164717613已通过匹配物理放置的启动汇编、IOFindBSDRoot及实际NativeUfs默认关闭返回检查。
QEMU小屏实际绑定17行普通日志、16行panic。另用完整内核在无UFS控制器的QEMU中触发预期
controller not ready for takeover，停止在DebuggerTrapWithState，确认独立快照state=2、16行绑定，
截图实际显示stage/prepared/published/reads/failures；没有把此预期控制器失败当作物理UFS测试。
AArch64 writer忙回归和6项封装测试通过。

新临时实测镜像out/macos26-ufs-panic-hardware-40164717613，150663168字节，
SHA256 faa5a27a574f47968f790400aec6fb99ac2be54d9f55ffc9a68315ef78ad27f5。
菜单版本A2FEEAC1，资格及截图在private/experiments/20261025-native-arm64e/ufs-panic-40164717613。
尚未部署；实机仍未证明目标根卷挂载。旧6F504502部署镜像和ADT已销毁，内核符号、输入、视频和恢复备份保留。
下一轮仅需记录独立PANIC DETAIL中的媒体与I/O计数，再决定修复哪一层。


### A2FEEAC1实机首次读到媒体列表与I/O计数

113秒视频已保存，独立PANIC DETAIL实机可读，prepared=1、published=1、reads=12、failures=0。
IOMedia包含disk0（0x5e008600字节）及disk0s1（0x5e000000字节），分区GUID
5878145C-6D81-4FB7-8057-14FF5AC18457与离线BaseSystem GPT相符。
目标APFS卷808EAC5E-8275-478D-814C-2229D8EB8D07没有出现在列表中。
这次证明GPT子分区已发布且传输未报告错误；不能仅凭success计数保证所有读取字节正确。
最后普通日志为swcrypto_threadpool_init:1133: Starting ThreadPool，未见其1155行或dev_init。

原发布线程在早期根设备start后立即计时，30秒即panic；APFS初始化和线程池就绪并不受此线程控制。
0034延长有界等待到180秒，仍只接受目标UUID且祖先为本窗口的IOMedia；每10秒报告读取/失败计数与busy，
超时媒体条目增加Content、busy及实际类名。测试覆盖45秒后就绪、截止点、永不就绪和错误身份，ASan/UBSan通过。
这用于检验是否提前中止初始化，不宣称已修复物理根卷失败。已有QEMU离线对照受GDB停机影响，
不能用其成功证明真实30秒窗口充足。新候选待编译及同一发布路径验证。

视频位于private/device/ufs-panic-40164717613/hardware-boot.mp4，详情帧及结构化观察已保存。
本轮随后正常恢复Android，a槽可启动，sys.boot_completed=1，未刷写分区或变更槽位。


### 新候选在30秒后发布目标卷，已具备实测条件

CI40166730488成功，实际UFS源码SHA匹配0034；反汇编等待比较常量为180000（0x2bf20），
100毫秒暂停递增，未绕过UUID或祖先检查。候选UUID 40AD15FD-6BA0-3834-BC05-B6B36A2F0F65，
SHA256 def31f2d8d4dc75c492501a7dc5f248bf5f24702c633ddbbecb5daa32283b81e。
匹配物理放置的启动汇编、IOFindBSDRoot、实际UFS默认关闭返回及独立panic面16行绑定均通过。

同一NativeUfsBlock离线读取对照在elapsed=30000 ms时仍打印waiting、busy=1，随后才出现
目标卷ready、BSD root: disk1s1和load_init_program。这是旧30秒窗口不足的运行时反例，
但底层hostBringUp和GPT解析被明确替换，不能据此断言实机唯一故障已解决。
8519次模拟读取69771264字节；原版存储、GPT子盘和APFS卷发布实际执行，VirtIO节点禁用。
现场位于private/experiments/20261025-native-arm64e/ufs-root-wait-40166730488。

新部署包out/macos26-ufs-wait-hardware-40166730488，临时RAM启动，原根卷和布局保持原样。
旧A2FEEAC1部署镜像与ADT已销毁，视频、诊断、内核符号及恢复备份保留。
新包尚未部署；下一轮录像应覆盖最长180秒发布等待，读取每10秒进度和最终详情。


### sheng实机挂载BaseSystem并进入PID1的dyld用户态

40AD15FD临时启动视频已保存。实机显示目标OS卷ready、apfs_vfsop_mountroot、
macOS Base System的mount-complete；内核尝试加载/sbin/launchd，随后输出
[1(launchd)]及原版Darwin Ignition Sequence/libignition参数。这证明本轮已经挂载根卷并执行PID1的用户态dyld。
视频最后停在ignition level=0x5、force dylib root=0、halt after stage=n/a；没有launchd主函数执行证据。
不能把进程名launchd或dyld日志等同于launchd完成初始化。

延长根卷等待后的首次实机已越过原根卷阻断；无需重写BaseSystem或调整分区。
视频168.874667秒，保存在private/device/ufs-root-wait-40166730488，root-mounted-140.png记录挂载完成及用户态输出。
当前等待用户确认视频之后画面是否继续变化，尚未要求重启设备。
下一步核对Ignition等待。配套XNU已有dyld_flags启动tunable，原版dyld的bit3为skipIgnition，
先用同一候选及离线读取后端验证dyld_flags=0x8，不伪装VMM或Image4返回值。


### Ignition后的停留已确认，启动tunable对照未越过等待

用户确认40AD15FD实机仍停在libignition参数，随后正常恢复Android，a槽及boot_completed=1已确认。
同一内核的NativeUfsBlock离线读取对照只增加dyld_flags=0x8，实际内核变量读回8，
用户态dyld已执行，但180秒内原版launchd的LC_MAIN没有命中；QEMU专用开关仍为0。
该对照不代表物理UFS仿真，hostBringUp、RootLayout及底层读取使用已记录的离线替身。
现场保存在private/experiments/20261025-native-arm64e/ufs-dyld-flags-40166730488。

配套dyld通过commpage读取skipIgnition，XNU的启动tunable只更新变量；sysctl写路径才同步commpage。
0053为显式开发根增加-sheng-development-no-ignition，保留CSR_ALLOW_UNAUTHENTICATED_ROOT要求，
仅在SHENG的DEVELOPMENT/DEBUG配置执行，不改变Image4验证结果，不设置VMM身份。
旧QEMU专用参数继续要求实际VMM。观察器新增实际commpage读回。
硬件封装另要求同一UUID/内核哈希、开发开关实际启用、commpage bit3及原版launchd主函数执行证据。
CI40169005156正在编译；此时尚未取得修正版运行结果。


### 原生UFS发布路径的离线对照已执行原版launchd主函数

CI40169005156成功，候选UUID D86D84A7-140B-31C0-9747-4BB27D57E3F7，
SHA256 bed5f1231b8572527d11fe9933edf676bae4ae2624a299aad611b3240abcdcff。
0053的显式开发开关读回1，旧QEMU专用开关为0，dyld实际commpage为0x9。
同一生产NativeUfsBlock、原版存储栈及APFS发布路径继续到PID1用户态，
实际启动栈取得原版launchd的LC_MAIN 0x104bf3480，首条PACIBSP完成后PC为0x104bf3484。
16字节指令与25F71配套launchd相符。日志出现hello, launchd及BaseSystem environment starting，
随后执行mount/apfs_boot_util，采集507次主函数之后的选定系统调用，未耗尽预算。

该对照仍以离线输入替换hostBringUp、RootLayout及底层块读取，不是物理UFS仿真。
10851次替身读取共151805952字节；后续mount-phase-1因缺少iSC/xART角色卷而失败，
不能据此宣称恢复系统已完整启动。现场、截图、实际commpage及主函数执行记录保存在
private/experiments/20261025-native-arm64e/development-dyld-40169005156。

匹配sheng物理放置的启动汇编、根发现入口、独立panic显示及真实NativeUfs::start默认拒绝均通过。
默认拒绝观察首次误选NativeUfsBlock::start，等待超时且未获得返回证据，不用于准入；
改用实际NativeUfs::start后完成真实返回，x0=0且四个硬件/媒体计数均为0。
开发版封装准入的7项测试已通过，本次实际封装也通过原版launchd主函数与commpage检查。

临时镜像out/macos26-development-dyld-hardware-40169005156，菜单D86D84A7，
SHA256 e33422851df8ed81379452e1549b3de03c912d7d9b9ed7a438f9fc0156d61b08。
用户确认可录像后已发送一次，a槽可启动，Booting OKAY；未写分区或变更槽位。
实机执行结果仍待录像，不能把boot确认当作launchd已在sheng运行。
旧40AD15FD部署镜像和ADT及本轮一次性ESP副本已删除，配套内核、符号、输入、日志及恢复备份保留。


### sheng实机已运行原版launchd并执行恢复系统启动任务

D86D84A7本轮300.629333秒视频已保存，画面需旋转180度。
138秒可读到disk1s1挂载macOS Base System，142秒出现显式开发根skipIgnition启用及/sbin/launchd加载，
148秒开始打印原版hello, launchd、Darwin Bootstrapper，152秒可读到BaseSystem environment starting及system域创建。
随后mount[2]和apfs_boot_util[2]实际执行。至此实机已越过Ignition并运行原版launchd；
证据来自用户态日志及其启动任务，没有把QEMU主函数断点地址说成实机采集地址。

后续重复出现iSC角色节点等待，205秒可读到role 5节点超时、role 256 on iSC: No such file or directory。
最终FIRST PANIC/PANIC DETAIL保留userspace panic: boot task failure: mount-phase-1 - exited due to SIGABRT。
该行为与离线单OS窗口输入一致，下一阻断是恢复系统所需iSC/xART角色卷环境。
目前没有完整恢复启动、WindowServer或桌面成功的证据。

视频及逐时画面保存在private/device/development-dyld-40169005156，
结构化观察及关键帧同步到private/experiments/20261025-native-arm64e/development-dyld-40169005156。
本轮没有刷写新分区，实机当前停留于panic现场，待返回FASTBOOT后正常恢复Android。

### 原生UFS双窗口已在离线读取对照中挂载全部ISC角色卷

CI40177580007成功，候选UUID4423A7AA-98AB-338F-9401-9BE0979716CB，
SHA256 3bd193607b7ff09c24058be0c14af5f981e273548c3a92bd172cf8be0776ffa6。
此前CI40176660878未启动runner，GitHub明确返回Billing/spending limit拒绝；用户处理后本轮已完成。

0035接入生产NativeUfsBlock的OS和ISC双窗口，先发布ISC并等待匹配UUID及实际窗口祖先，随后发布OS。
OS保持只读；ISC以只读种子配合最多64MiB驻留数据的稀疏RAM写入层，需显式native-ufs-isc-overlay=1。
0036将共享SparseDisk头中的普通静态辅助函数改为static inline，修复macOS编译器的Werror诊断。
共享生产读写算法已通过短复制、部分写入、容量上限、底层读取失败和不可变种子的ASan/UBSan测试。

本轮离线对照使用生产块设备、分区及原版APFS组件，底层hostBringUp、RootLayout和UFS读取由受限镜像替身提供。
11397次替身读取共168779776字节，两个窗口实际发布，读取失败0。
原版apfs_boot_util先后挂载SHENG-xART、SHENG-Preboot和SHENG-Hardware，原版launchd继续执行后续启动任务。
这确认已越过此前mount-phase-1失败，但不是物理UFS仿真或本版实机通过。
本轮未观察到ISC写入或同步请求，不能以挂载成功宣称完整IOMemoryDescriptor写入及刷新路径已实测。

初轮只分配512MiB内核内存，原版临时Data创建再次触发已定位的tmpfs预算限制，
最终restore-datapartition exit(1)。按既有实机3GiB内核分配继续运行4GiB QEMU对照，结果另记。
配套启动汇编、根发现入口和NativeUfs::start默认拒绝已通过；默认拒绝实际返回0，四个硬件/媒体计数均为0。

双窗口根镜像已准备，尚未写入平板。新增增量工具只向现有macosroot尾部写ISC，
校验其回读后才提交4KiB清单，最后全镜像回读；不修改GPT、Android userdata或原有BaseSystem。
发生清单写入确认超时时记录未知状态，不自动重试。5项更新失败路径与9项封装准入测试通过。
源码参考及按启动阶段排序的接入条件见docs/droidvm-reference.md。
所有运行日志与画面仅保存在本地，当前设备保持Android。

### 同一UFS候选已执行临时Data和恢复系统服务，图形仍未接通

4GiB QEMU、3GiB连续内核分配复测已完成临时Data、模板复制和后续启动任务。
原版recoveryosd输出Establishing an Aqua Session并创建审计会话100001，
configd、fskitd、securityd及WindowServer已有执行日志。尚无可用图形界面证据。

生产ISC写入层实际完成14次写入、4次同步，驻留数据118784字节，写入层及块设备失败均为0。
底层读取替身共16373次、287096832字节，未提供底层磁盘写入入口。
封装现在额外要求同一候选实际出现ISC写入与同步，低内存仅挂载对照不能单独取得实机准入。

调试器读取替身的一次continue可包含多次I/O，超出外层180秒截止后仍继续服务读取；
本轮通过QMP外部暂停结束观察并保存真实寄存器及日志，未伪称内核自行停止。
未见最终panic，但这是人为结束的有限观察，不能据此宣称长期稳定。
控制台记录82字节busy-writer丢失，不能称为完整无损日志。
现场保存在private/experiments/20261025-native-arm64e/ufs-isc-40177580007/recovery-services-4g。

### ISC已追加到实机macosroot并完整回读，新版待录像

仅向原macosroot的1579155456字节处追加2149580800字节ISC种子，再提交4096字节双窗口清单。
没有重写原有BaseSystem，没有GPT、槽位或Android userdata变更。
全根3728736256字节回读SHA256为3246bc6e88aea6d20c0f1296b24d8510274ae3526d8ecd5a6f3200a9182c7b44，
与准备好的镜像完全一致，Android已恢复boot_completed=1、a槽。

Recovery Toybox不支持iflag=fullblock，首轮在写入前的读取校验退出，没有写分区；
改用实际支持的count_bytes，以字节限制ADB管道短读，设备RAM临时文件已验证限制有效。
实际写入后，分区节点读到新清单，父sda节点仍读到旧清单；显式flushbufs两条路径后结果一致。
保留初次失败记录，随后只读复核并完成全镜像SHA，不重试写入。
更新工具已加入别名缓存刷新，定向测试模拟独立父节点缓存。

新版菜单SHENG macOS 26 - UFS+ISC 4423A7AA，容器150663168字节，
SHA256 27fadeccda9f171d77eecdc94c63c0b752b131085452c6958b780c4df96a3460。
封装实际通过同UUID启动汇编、根发现、默认拒绝、三个ISC角色卷及真实写入/同步的检查。
当前仅已具备实机临时启动条件，尚未发送这版；用户录像准备待确认。
旧D86D84A7部署镜像和ADT已移除，配套原始内核、符号及视频证据保留。


### 实机ISC与临时Data已通过，改用运行时文件快照保存日志

4423A7AA的528.704秒实机视频已保存于本地private/。145秒出现原版hello, launchd，
160至170秒依次完成SHENG-xART、SHENG-Preboot、SHENG-Hardware挂载。
185至195秒临时Data和模板复制继续，275至525秒持续出现新的XPC服务启动记录。
未见最终panic或整机重启，未捕获实机Aqua Session或图形Recovery，不能移用QEMU的图形会话结论。
重复bootstrap的error 37和不适用OS变体的error 158均不是对应进程的退出码。
设备本轮已正常恢复Android槽a，boot_completed=1。

旧UEFI日志恢复器缺少内部UFS的BlockIO后端，macoslog只有人工观察文件，
NEXTLOG/捕获文件与RAM跨重启保留仍未实测通过。
新增0037让NativeUfs在运行时显式启用native-ufs-macoslog=2后保存保留日志，
mode 1仅验证，默认关闭。文件由Recovery在既有FAT16中预分配，内核不修改FAT或GPT。
两个1MiB槽交替保存82048字节日志快照，先写载荷并同步，再写CRC提交头并同步。
写入仅限LUN4中已验证的SHENGLOG.BIN数据块，末尾保护块禁止写入；验证或命令失败立即停止。
保留16KiB前缀、64KiB尾部及丢失计数，不等于完整流式历史，也不保证panic前最后两秒。

本地生产解析器、提交算法和worker已通过FAT镜像副本不一致、碎片、交叉引用、GUID/重叠、
逐步断写恢复、默认关闭、只读验证、重启序号和错误停止测试。
实际生产UFS命令通过LUN4边界与SYNCHRONIZE CACHE目标LUN测试；
QEMU还验证RAM快照不夺取忙碌writer，且原有panic文字区保持独立。
当前这些结果不包含新候选完整XNU启动或物理UFS日志写入，尚未宣称实机修复完成。


既有macoslog的64MiB FAT16完整备份已保存。原有空闲簇洞会让普通mcopy生成碎片文件，
离线预分配已改为只从原始空闲簇中选择连续2MiB，并逐簇核对原有FAT链、目录项和数据未变。
SHENGLOG.BIN已在实机创建，首LBA448535，文件末块为只读归属标记。
整分区回读SHA256为1efe6fe6550711cb327213553adeb7f9ec162b00bd3c805980b678fb6956007d，
与准备镜像一致；主备GPT保持原样，设备再次恢复Android槽a、boot_completed=1。
此时文件尚无内核运行时快照，不能把预分配成功写成内核日志写盘成功。


### 运行时日志候选已编译，完整XNU文件验证进行中

CI40185402114通过，接入原版恢复组件后的UUID为4F62754E-8ACC-3090-8892-C12EB721BA16，
内核SHA256为45d1c2c0318f0aa7c160cf3902f53fa0a507899df96a8f0f3827c17c618db266。
早期候选的volatile递增不符合Xcode27的C++23规则，已改用原子计数并按C++23验证。
快照函数先前声明为weak_import，被显式导入准入拒绝；已改为必须由配套内核提供的强依赖。

新的QEMU后端仅替换hostSubmit以下的控制器传输，使用真实IOLock、内核分配、
RootLayout解析、UFS命令构造及macoslog worker；测试介质来自本地真实GPT和预分配FAT镜像。
本版启动汇编实际16格、IOFindBSDRoot及NativeUfs::start默认拒绝均通过。
mode 1已通过，日志文件首LBA448535，8589次读取、写入0、同步0。
mode 2已生成可解码快照并运行原版launchd任务，完整最终结果及物理写入另行记录。
该QEMU后端不是物理UFS仿真，不能替代实机写入和Recovery回读。


本版完整XNU日志验证已完成：25份快照，50次WRITE(10)、50次SYNCHRONIZE CACHE，
每轮实际遵循payload-write/sync/header-write/sync，错误0。
文件回读UUID及generation与停止现场一致，保留48098字节控制台内容，busy-dropped=0。
只读模式未写入，默认拒绝实际返回0；文件外区域和末尾保护块均保持一致。
原版launchd主函数执行，ISC三个角色卷挂载，ISC RAM层7写2同步、57344字节驻留、失败0。
以上使用QEMU控制器传输替身，物理UFS写入尚未通过；需要临时启动后Recovery读回才能确认。


### 实机运行时日志写盘与重启后读取已通过

4F62754E候选临时启动后，视频记录NativeUfs验证日志文件并提交第一份快照。
随后从root Recovery只读导出SHENGLOG.BIN，两个提交槽均有效，序号为44和43，
最新快照UUID与本次内核一致。运行前文件载荷为空，确认本次数据不是预置的QEMU捕获。
完整macoslog分区读回与预分配镜像比较，文件外字节、FAT、其他文件、保护块和主备GPT均未改变。
设备已恢复Android，boot_completed=1、槽_a。

最新快照记录控制台累计218024字节，保留81920字节，省略136104字节，busy-writer丢失82字节。
这是运行时保留前缀和环形尾部的持久快照，不是完整流式历史，也不保证最后一次panic已提交。
旧UEFI恢复器和RAM跨重启保留仍未通过；本次写盘不依赖这两条路径。
通用解码器不自动认证硬件来源，本次实机资格由独立的空文件基线、启动视频和Recovery回读记录共同确认。
视频、原始日志和分区镜像仅保存在本地private/。

持久日志已确认实机WindowServer进入运行态，pid85在3824毫秒后以exit(1)退出，
随后launchd再次创建pid87。logd及opendirectoryd查询失败出现在退出之前，但尚不能证明其为退出原因。
此前QEMU的原版SkyLight退出调用栈定位到HID和display/cursor初始化；实机目前只确认退出码及重启，
下一步按实际IOKit查询和用户客户端返回值定位，不能把QEMU的失败位置直接作为实机结论。
保存的首次EL1同步异常寄存器位于bzero+0x20，日志在此后继续进入用户态，不能当作最终致命panic。
图形Recovery仍未显示。


### QEMU已解除WindowServer的IOHIDSystem初始化阻断

对当前4F62754E原生UFS候选重新取证，原版SkyLight查询IOHIDSystem时，
IOIteratorNext实际返回0，随后进入此前定位的HID失败退出分支。
同一原始内核及UFS组件加入25F71原版IOHIDFamily与声明依赖后，
WindowServer查得服务端口0x1703，IOServiceOpen(type=0)返回0，
IOHIDCreateSharedMemory(version=4)也返回0。两组均由实际EL0断点、原始指令前缀、
编译器导出的当前进程归属及该进程的共享缓存slide核对，未改WindowServer或函数返回值。

新增--hid-components显式选择配套HID组件，要求同时启用--recovery-components，默认行为不变。
该配置生成的候选SHA256为a9c2ffb86243690f724778a927a7c9de11490d08318b1355bb3706e1147c3caf，
与先用--include-module构造并观察的候选字节一致。
这只证明QEMU通过HID服务打开与共享内存初始化，尚未证明WindowServer持续存活、显示提交或实机HID。
原生16KiB/47位内核、原版launchd及UFS根盘解析仍实际执行，控制器传输继续使用离线替身。

观察器补丁0038支持在互斥成功/失败分支处结束观察，并逐条保存真实用户调用记录。
此前180秒观察未到选定调用，480秒观察在互斥分支等待中超时且未保留局部记录；这些工具失败不算内核失败，
也不作为HID验收。修正后的正负对照已分别在真实终点结束并保存完整gdb-stop记录。
所有原始控制台、调用参数及退出栈均留在本地private/。

下一阶段是显示服务发现、帧缓冲模式和画面提交。现有UniXNU显示ABI明确针对iOS17，不能直接套用26.5。
Libm中的115处线性解码阻断已定位到六段数学常量池，按固定UUID、完整哈希及前后RETAB/PACIBSP边界识别。
19项内容、边界及UUID变异均被拒绝；真实函数前导指令不在排除范围内。
包含IOMobileGraphicsFamily、IOSurface及依赖的30组件候选已在QEMU运行到原版WindowServer的HID共享内存返回，
服务端口0x1703、打开和共享内存返回值均为0。候选SHA256为
c4d8c5259ad9bcb82cdc4ecaff9aba10ef19d78e17fa63ceb0a3bc8730eeebdd。
本次在HID返回处结束观察，不能证明WindowServer持续运行或图形Recovery已显示。

### 默认关闭的GOP显示驱动已接入构建，运行资格待验证

新增可选--build-gop-display，要求ARM64E内核及UFS companion。
源自DroidVM固定提交1dfb172的CPU scanout实现，移除VM GPU身份及macOS27到26.5的swap转换，
保留原版26.5显示家族的队列、用户客户端及通知。
source/ABI header单独获取并验证固定哈希，仓库只保存增量补丁和构建工具。
驱动仅在native-gop-display=1且cpus=1时尝试启动；默认关闭，不表示GPU加速。
新画面提交时停止普通启动文字覆盖，RAM及持久日志保留，panic面板独立。

本地已核对M1和vma2的473槽名称及PAC判别值、144/6904字节的基类实例尺寸，
并对旧版参考与M1的legacy函数指令形状和字段位移作比对；PC相对地址归一化不证明外部调用目标等价。
实际预链接还要求固定M1显示家族UUID及代码段哈希，并核对编译后的473槽和PAC元数据。
源文件/ABI输入变更与补丁上下文漂移均有拒绝测试。
CI40197549427已通过编译和链接。参考头漏掉的8字节基类状态区已补齐，编译时断言144/6904字节尺寸。
GOP属性改为内建屏，避免原版框架将其仅列为外接屏而不选作主显示。
预链接候选SHA256为a06e14be4bc73d27adea38487e024f70d7ae2cabaabeada34768f0fe40f78c2f，
显示473槽、存储326槽及PAC元数据审计均通过。79项非导出继承函数只允许绑定原始对应vtable槽，
直接调用、其他槽位或PAC变化会被拒绝；没有引入返回成功的替代函数。
四个纯虚函数覆盖槽按原版IOMobileFramebuffer的首次声明核对，不能使用抽象派生类的纯虚占位签名。
尚未通过原生服务发现、实际交换帧和WindowServer持续运行验证，暂无新实机测试镜像。


### QEMU原版WindowServer已完成GOP显示服务枚举

同一a06e14be候选中，NativeGOPDisplay实际启动800×600、row3200。
原版WindowServer到达IOMobileFramebuffer的显示枚举完成路径，
参考管线数1、已枚举数1、显示记录数1；实际EL0指令前缀、进程归属及共享缓存slide均匹配。
观察在该路径主动结束，没有改变用户态指令或函数返回值。
这解除服务发现阻断，尚未确认主显示客户端打开、IOSurface交换或图形Recovery。
控制器传输仍为QEMU替身，不能据此认定sheng物理帧缓冲适配通过。

观察器0039按实际线程及原SP等待共享区域系统调用返回，限量跳过其他线程命中的共同返回地址，
避免把调试工具的进程选择失败误报成内核异常。
本轮正常返回路径已实际通过，未遇到额外线程返回；跳过分支仍未取得本轮运行覆盖。
原始日志、进程状态和屏幕捕获仅保存在本地private/。


随后同一候选在原版WindowServer的显示打开函数返回路径取得0，输出连接非空，
输入显示记录的primary标志为1，入口与返回属于同一实际线程。
至此QEMU通过显示服务枚举与客户端打开；没有改用户态指令或返回值。
本轮0039实际跳过一次其他线程命中的共享区域返回地址，再等到原线程返回0，
补齐此前未覆盖的线程选择路径。下一项是实际IOSurface帧复制及交换完成，图形Recovery仍未验收。


继续运行至开屏请求后，保留日志出现NativeGOPDisplay: display on，
随后WindowServer pid80触发core dump处理，pid101再次启动。
本轮535秒传输预算内没有命中整帧复制完成点，也未记录first swap submitted；
最终由QEMU控制器替身的时间预算停止，不能把该停止PC当作内核panic或显示函数故障点。
屏幕仍为文字控制台。当前阻断已移至显示打开及开屏之后、首次帧提交之前，
异常原因仍需实际用户态异常寄存器及调用栈确认，不能据此认定PAC或GPU为原因。


### 首帧前阻断已定位到原版Metal设备检查

真实exception_triage入口取得WindowServer的EXC_CRASH，code[0]=6<<24、code[1]=0，
对应SIGABRT，原始异常类型及code位均为0。EL0 PC位于__pthread_kill，
指令字节与25F71缓存一致。按该进程实际共享区域slide符号化的调用链为
pthread_kill、abort、WSSystemCanCompositeWithMetal的once block，
再到WSCompositorActivateDefault与WSInitialize。
原始PAC值保留，移除元数据仅用于47位地址查找，不宣称对栈记录作了指针认证。

原版block等待30秒后构造“No suitable Metal devices present after %llu seconds.”，
随后调用abort，与实际调用栈和SIGABRT相符。本次退出不是PAC认证故障，
但不代表所有ARM64E路径已经验收。
GOP显示发现、客户端打开和开屏请求已通过，尚无可用Metal设备及第一帧。

DroidVM的NativeAdrenoMetalPlugin经IOGPUMetalDevice加载，创建的设备向Metal注册，
底层仍依赖NativeBridge、Turnip和GPU用户客户端。单独复制显示驱动不能补齐该链路。
25F71 SkyLight内保留CompositorSW及默认合成器选择路径。
下一项先验证原版软件合成入口和实际输出，再评估配套Metal前端及原生GPU后端。
软件合成路径目前只有静态入口证据，不能宣称可用或已有图形Recovery。


### QEMU已进入软件合成激活路径，第一帧仍未通过

显式QEMU实验在实际WindowServer进程的默认合成器once block处，
核对原版88字节哈希及共享缓存slide后，以16字节叶函数设置原有软件合成选择位。
本实验修改了客体内存中的代码，未改原始磁盘文件；不是未修改用户态的验收结果。
不删除PAC指令，不修改寄存器返回值，也不引入假的Metal设备。
随后同一线程确实到达原版activate_compositor_sw入口，解除默认选择阶段的Metal等待。

但535秒传输预算内未命中复制完成点，未看到first swap submitted，WindowServer仍退出并重启。
目前只证明软件合成激活入口可执行，不能证明软件合成器完成初始化、成功渲染或图形Recovery。
后续按实际异常和调用栈定位新退出点，不能把之前的Metal等待原因套到本次退出。
一次前置运行尚未启用实验时触发中断屏蔽超时，已保留现场；
QEMU后续使用原版interrupt-masked-debug-mode=1记录该超时，实机配置保持不变。


软件合成后的首次退出已捕获：EXC_CRASH/SIGABRT调用栈仍经过原版Metal等待block，
但调用方变为set_ca_window_shadows_enabled的once初始化，再返回activate_compositor_sw。
因此只改变默认合成器选择不足以绕过共享能力检查。
后续QEMU实验改为在原版Metal检查once block内返回“无设备”，让dispatch_once自然完成，
保留PACIBSP/AUTIBSP及原版软件合成、阴影禁用判断；此方案仍需帧输出验证。


### 软件合成已进入显示更新，退出点转为IOSurface格式

配套25F71 QEMU实验在原版Metal能力once block的PACIBSP之后核对原始代码哈希，
执行配对AUTIBSP/RET，使原版dispatch_once正常完成并保留“无设备”结果。
原始磁盘保持只读；该显式实验修改了客体代码，不能作为未修改用户态的验收。

实际WindowServer已进入SLCADisplay::render_update、UpdateDisplays与显示定时器路径。
新异常仍是EXC_CRASH/SIGABRT，调用点为WSCompositeDestinationCreateWithIOSurface+0x1cc，
对应原版“Unimplemented pixel format”分支。当前没有首次swap或完整帧复制证据。
格式数值正在通过原版IOSurfaceGetPixelFormat的实际返回点读取，尚不据此猜测具体格式。

GOP候选补丁把IOAV颜色元素从Default RGB的16改为sRGB的10，
与已公布的8-bit SDR模式及色度一致。依据为本地固定Snapintosh实现，
并结合当前25F71原版格式选择及软件目标创建代码核对。
补丁准备流程已验证：相对既有编译输入只有该常量与英文约束注释变化。
运行结果仍需新构建验证，不据此宣称已有图形Recovery。


实际只读观测与crash annotation已交叉确认格式为RGhA（0x52476841 / 1380411457），
不是猜测的10-bit格式。sRGB常量的单变量QEMU实验仍得到RGhA并退出，
说明颜色声明修正不足以解除当前阻断。构建40208410649已通过，仍未取得帧输出。
下一项显式QEMU实验在原版framebuffer_pixel_format分配决策处选择BGRA，
保留PACIBSP与AUTIBSP，不修改现有IOSurface的格式字段或查询返回值。


### QEMU取得原版WindowServer第一帧，尚无Recovery窗口

显式开发实验已让原版framebuffer_pixel_format在分配之前选择BGRA。
原版IOSurfaceGetPixelFormat随后实际返回BGRA（0x42475241），
不再进入RGhA不支持分支。原版软件合成、IOMobileFramebuffer交换队列与GOP复制继续执行。
实际停止在copySurface完整复制循环之后、帧计数写入之后，计数为1，
不是控制器预算停止，也没有捕获到WindowServer异常。

800×600 RAMFB截图为黑色背景和鼠标指针，尚未出现Recovery窗口。
这证明首次像素呈现，不能当作完整图形Recovery或GPU加速验收。
实验保留PACIBSP及AUTIBSP，只修改QEMU客体中的Metal能力block、分配格式选择及sRGB常量；
原始磁盘文件未修改，尚未部署实机。

sRGB源码修正的构建40208410649已下载并完成30个原版模块及显示伴随模块重链接，
新UUID为43E660E5-73B4-30E3-B998-A82D62224439，
候选SHA-256为5f555e6fa0d5b5975804de138c79430aaafcd18a53c93daf39e518d136442d68。
配套DWARF各调试section与前一构建逐字节一致，进程布局据此复用并重新绑定新候选身份。
编译后的sRGB声明已用于下述连续帧验证。


同一新候选的连续帧观测已完成：原版WindowServer依次将GOP完整复制计数推进至1–10，
每帧每行复制3200字节，共600行，实际表面BGRA；未触发WindowServer异常，未耗尽传输预算。
本次sRGB声明来自已编译伴随模块，未在运行时修改内核代码；
仍有明确记录的两个QEMU用户代码开发补丁：Metal能力once block与分配前BGRA选择。
第10帧截图仍为黑底鼠标指针，因此当前验收限于连续呈现，不含Recovery窗口。
下一项定位恢复界面客户端及窗口显示链路，再决定实机部署方案。


### Recovery客户端已进入AppKit，仍未创建可见恢复窗口

连续帧之后的有界运行没有出现LanguageChooser或RecoverySpringboard。
原版recoveryosd仍存活，其最后的用户栈为SecKeychainLogin → StorageManager::login →
Keychain构造 → check_system_keychain → read；内核保存栈同时确认socket读取等待。
配对25F71代码检查的是/var/run/systemkeychaincheck.done，并从
/var/run/systemkeychaincheck.socket等待就绪，尚未创建Aqua会话。
原版systemkeychain的一个线程停在CSSM_Init调用的阻塞式ASL日志发送中；
仅凭这一份快照不能断言syslogd已死锁或SEP是原因。

显式QEMU对照只省略上述void就绪检查，保留原版SecKeychainLogin及其返回值处理。
recoveryosd随即越过socket等待，进入真正解锁路径，随后在
__SecLookupIndirectUnlockKey → NSXPCConnection → 同步Mach回复等待中停留。
按配对框架的SecuritydXPCClient初始化代码，目标服务为com.apple.securityd.general；
配对LaunchAgent将该服务交给/usr/libexec/secd。
短观测只能证明该时刻的等待，不能据此认定调用永久不返回。

以上实验仍使用只读根镜像、同一编译sRGB候选和明确记录的软件合成/BGRA开发补丁。
就绪检查补丁只修改QEMU客体内存，未修改原始磁盘文件；共享缓存页可能被其他客体进程共享，
不能宣称是进程私有补丁。线程及日志证据保留在本地private/，未上传。


同一就绪检查对照延长至传输预算结束后，recoveryosd已越过实际钥匙串登录，
停留在原版ROSAgent::runAquaSpecificTasks的同步XPC调用中。
原版RecoveryOS Agent已启动，其主线程保存的用户边界与栈为
NSApplicationMain → NSApplication::run → finishLaunching → 主菜单初始化。
该线程在快照中可运行，不能把这个边界当作卡死函数。
截图仍为黑底鼠标，未发现LanguageChooser或RecoverySpringboard。

独立省略SecKeychainLogin调用的负对照没有产生恢复窗口，未作为部署方案。
该实验只在核对实际recoveryosd头部、调用点字节及配对Security入口后调整QEMU的PC，
没有伪造认证返回值，也没有修改原始文件。它与保留登录的对照都出现了旧ASL链上的等待：
secd部分工作线程在os_log的syslog镜像发送及日志锁上等待，recoveryosd也有ASL锁等待。
syslogd仍有可运行线程，因此当前证据是日志转发阻塞及其连带等待，不是已证明的永久死锁。
单变量对照已关闭QEMU中的旧syslog镜像，保留原版钥匙串就绪检查、登录与恢复会话流程。
该对照仍未产生恢复窗口：最终recoveryosd线程停留在check_system_keychain的socket读取，
systemkeychain等待PID91的bash子任务，syslogd还有写入中的线程。
期间出现的Force enable input device日志不能作为钥匙串登录完成的证据。
因此单独关闭旧镜像不足以解决就绪等待，也不把此前瞬时XPC等待归为永久死锁。

已启动更长的QEMU观察，沿用曾到达RecoveryOS Agent的就绪检查对照，保留真正钥匙串登录。
这次扩大最终只读线程快照至最多96个进程，包含子shell，避免只记录父服务而遗漏实际子任务。
运行结果尚待确认，未封装或部署到sheng。


### 延长运行捕获RecoveryOS Agent应用注册异常

延长运行已结束，停止在真实_exception_triage，实际进程为RecoveryOS Agent / PID130。
异常为EXC_CRASH，代码包含SIGABRT；并非传输预算耗尽。
按该进程实际共享缓存slide 0x6E8000符号化，调用链为
NSApplicationMain → NSApplication::init → 菜单栏上下文初始化 → GetCurrentProcess →
_RegisterApplication → HIServices的RegisterApplication block → abort → pthread_kill。
因此原版恢复应用已进入AppKit，但本轮在应用注册期间退出，仍未呈现恢复窗口。

失败点是多个致命分支共用的abort入口，不能仅凭附近的版本错误字符串断言原因。
配对HIServices代码在该路径使用__crashreporter_info__槽保存具体消息；
下一次观察已增加对该槽指向字符串及有界用户栈的只读捕获。
完成原因确认后再处理注册所依赖的会话/服务条件，不把跳过abort作为注册成功。
原始日志、线程与寄存器保留本地，未部署sheng。


### 复现等待链显示旧日志镜像同时拖住注册与钥匙串服务

增加失败消息捕获的20分钟运行未复现上一次应用注册SIGABRT；最终由观察器预算中断，
这不能算应用注册已经修复。最终快照仍在SecKeychainLogin的DbCreate调用中，
securityd等待applekeystored的kb_load回复；applekeystored主线程则停留在os_log的旧syslog镜像发送。
launchservicesd的工作线程也在同一旧镜像发送路径等待。
这些是实际线程链路，不把日志不再增长等同于内核崩溃；只读CPU采样还显示WindowServer在EL0执行。

新的组合对照保留真正钥匙串登录和原版应用注册调用，合并已单独验证的就绪检查省略与旧syslog镜像关闭。
目的是检验关键服务不再被镜像发送拖住后是否能够返回，尚未执行缺少ASN的策略对照。
后者已准备，但仅允许在捕获到匹配的缺少ASN退出消息后运行，不伪造ASN或WindowServer连接成功。

### 原版RecoveryOS Agent越过注册，停留在设备所有者查询

保留原版钥匙串登录的两组组合对照均已结束。每个关键任务的实际用户页表读取确认，
旧syslog镜像关闭指令确实出现在securityd、secd、applekeystored、launchservicesd和recoveryosd映射中。
逐调用返回对照也确认原版PACIBSP与RETAB配对执行，未把认证返回值改为成功。
最终仍有钥匙串派生熵及服务初始化等待，没有LanguageChooser进程或窗口。

独立UI开发对照省略recoveryosd钥匙串初始化，并关闭旧syslog镜像。
该轮原版RecoveryOS Agent已越过此前的HIServices注册异常位置，主线程在
TRMUser::deviceOwners → AuthorizationCopyPreloginUserDatabase → com.apple.authd连接握手中等待。
画面已出现原版macOS等待光标，但未呈现语言窗口；这不构成图形Recovery验收。
此轮没有启用缺少ASN策略，也未伪造应用注册成功。

另外，runningboardd和RecoveryOS Agent工作线程在可选的os_activity_stream_reflect转发中等待。
它与此前旧syslog镜像是不同路径。新的对照关闭该可选转发，保留原始授权请求；
另一组仅省略设备所有者发现，并使用原版TRMUser已有的空列表失败路径，不伪造认证成功。
两组仍在QEMU运行，结果尚未确认。所有控制只用于本地开发，未修改只读恢复镜像或部署sheng。

### 延长观察与所有者查询对照实际命中

前两组后续已停止。第一组在LaunchServices应用签入及信任评估期间等待；
第二组已启动原版authd，并发出实际预登录数据库请求。
检查控制器发现，原观察器在WindowServer启动后撤销进程激活断点，
使第二组后来启动的RecoveryOS Agent没有布下所有者查询控制点；该组不计作省略查询的验证。

改为提前布点的下一组由20分钟传输时限结束，最终仍在lsd注册恢复卷中的应用，
没有命中所有者查询控制点，也没有语言窗口。这个停止原因是观察边界，不是应用崩溃。
现已启用每120秒保存一次的只读进程/线程快照，读取后继续同一客体运行，避免丢弃初始化进度。

最新长观察已取得两次连续现场：lsd从数据库种子注册进入服务器事件循环，
RecoveryOS Agent随后实际命中AuthorizationCopyPreloginUserDatabase入口。
核对原版可执行头部、调用点及清零的输出槽后，仅把该调用调整到TRMUser已有的空列表失败路径，
没有修改状态返回值或伪造认证成功。后续现场已在原版AppKit图标资源初始化中运行。
截图仍为等待光标；LanguageChooser窗口尚未出现，不能把以上进展算作图形恢复验收。

同时已准备原版ROSEnvironment的guest恢复模式选择。
该框架依次读取security.mac.asp.recovery_boot_mode、NVRAM恢复模式及__OSINSTALL_GUEST_MODE，
recoveryosd在模式缺失时可能跳过语言选择器。当前QEMU开发控制仅选择原有guest分支，
不伪造机器型号、ASN或授权成功；该控制点尚待实际命中。
