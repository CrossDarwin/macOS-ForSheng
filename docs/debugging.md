# sheng 内核现场与 KDP

当前25F71 ARM64E实机视频确认连续内核文字、NativeUfs: published OS、原版APFS和FSCompression加载。
最后仍在等待808EAC5E-8275-478D-814C-2229D8EB8D07，没有挂载或launchd证据。
40161755752实际包含0051，QEMU确认普通面板绑定24行；实机仍只显示首次panic摘要，没有媒体列表或读盘计数。
普通writer被打断时，旧panic正文的trylock也会失败；这是源码可复现的缺口，尚未证明是本次硬件唯一原因。
0052把首次panic正文保存到独立4096字节快照，并在普通24行下方预留16行固定文字区。
其像素和游标不与普通writer共用，不强行释放被打断的锁。AArch64 QEMU实际字体像素、writer忙、
RAM头已记录可恢复异常、嵌套panic及80行后续日志的固定显示已通过。新内核尚待CI及原生映射验证。

macoslog只读导出仍只有OBSERVED.JSON，没有自动捕获文件。
当前固件SHENG_VENDOR_HW=0，最终FD没有UFSDxe；DarwinBoot和Fat存在，但缺少内部UFS文件系统的物理后端。
手动恢复菜单实机出现，选择后返回；这不证明保存器成功访问内部存储。按用户要求暂缓该后端。
KDP和UART仍没有实机传输能力。

内部日志存储使用用户授权新建的`macoslog`：sde第78分区、64 MiB FAT16、标签`MACOSLOG`，PARTUUID `4cd2ed34-2142-4ea4-abf2-ec6c51d117d7`。
root Recovery已经实测挂载、普通文件写入和读回，并完成capture_persistent_log.py只读导出；`OBSERVED.JSON`是人工读取屏幕后的结构化记录，不是RAM导出。XNU仍没有已验证的UFS写入后端。新增DarwinBoot保存流程使用固件文件系统，宿主EFI服务测试已通过，跨重启RAM留存与实机UEFI文件系统枚举仍未验证。
禁止向现有厂商logfs或userdata裸写日志。64 MiB来自当前sde的未分配尾部，未调整原分区边界或Android数据大小；有效GPT及空闲区回滚备份保存在`private/backups/20261024-macoslog-partition`。

`0015-native-retained-log-persistence.patch`在加载下一份内核前读取macoslog上的NEXTLOG.BIN，核对指定RAM范围、日志头、内核UUID和物理地址。先独占原RAM页，再分配快照，防止分配快照时覆盖来源；原页已被固件占用或不具备恒等映射时拒绝读取。
固件只允许操作上述PARTUUID、名称、类型、起止LBA及4096字节扇区均匹配的64 MiB分区；需要PartitionInfo、BlockIo及SimpleFileSystem三个协议同时存在。不存在时打印跳过原因，不转向其他分区或裸写。
每次新增CAP00001等目录，保存NATIVE.BIN、CONSOLE.TXT、PANIC.BIN、REQUEST.BIN、STATUS.TXT；逐文件Flush并读回比对后才写DONE.TXT。中断目录保留且不重用，后续捕获不会覆盖它。
CONSOLE.TXT包含16 KiB前缀及64 KiB环形尾部，超出容量和writer忙时丢失的字节有明确标注；这不是整机RAM转储，也不保证无限日志。512 KiB panic区另外保留。
加载当前匹配内核后，从实际Mach-O符号和已分配PA生成下一次NEXTLOG.BIN，不猜测地址；上一次请求尚未成功恢复时保留原请求，不覆盖。必须重新进入含此加载器的UniXNU才会尝试恢复，进入Android或断电可能破坏原RAM。相同UUID也不单独证明属于最近一次运行。

0033修正旧恢复器与3 GiB窗口不兼容的地址限制。原范围0x880000000..0x8bb300000之外，
只增加实机UEFI RAM表中的0x8c0000000..0xa00000000；中间的外部abort间隔仍拒绝。
实际AllocateAddress独占页和逐页恒等映射检查保留，不扩大Linux RAM读取器的范围。
macoslog身份及尺寸匹配后，若文件系统协议尚未建立，只连接这个分区再查询FAT协议。
ARM.BIN及RECOVERY.BIN是固定16字节的最新加载器状态，分别标记请求建立和恢复结果；
只记录状态，不证明RAM内容已保存，也不证明来自最近一次内核。capture_persistent_log.py会同时解码。
如果日志卷本身无法打开，这两份状态也不能写入，仍需交接页错误作为依据。
宿主EFI测试覆盖高地址相距3 GiB的日志/panic、指定分区连接、错误状态读回、地址间隔拒绝、
现有CRC/UUID/短写/分配失败；实机跨重启捕获尚未验收。

保存现场前使用同一固件的小型恢复包，避免再次加载完整内核：

```sh
python3 scripts/package_native_log_recovery.py \
  --source-build out/macos26-ufs-logfix-hardware-40124513764/build.json \
  --output out/native-log-recovery-NEW
```

该包复用已核对的固件载荷，菜单读取不可执行标记。NativeLogSave执行后，ParseKernel拒绝标记并返回菜单；
它不申请新内核窗口、不重新建立NEXTLOG。返回菜单本身不证明日志保存成功，应从Recovery读回CAP目录和状态文件。
恢复入口在按键可用时取消自动倒计时，先停留菜单再由操作者选择。真实20 MiB FAT16文件在QEMU UEFI挂载后读取配置并显示recover菜单已通过；这不证明实机固件保存器已执行。
20 MiB恢复卷使用FAT16并校验簇数；此前强制FAT32只有40298簇，低于EnhancedFatDxe门槛，卷被拒绝，界面显示no boot entry found，保存器没有执行。

root Recovery只读导出：

```sh
python3 scripts/capture_persistent_log.py --serial 29d9c0be \
  --kernel-build private/ci/macos26-arm64e-kernel-RUN \
  --output private/experiments/CAPTURE
```

脚本不自动重启，不改分区；核对sheng/root Recovery、sde78、主GPT CRC与分区GUID/边界及FAT16卷后只读挂载，导出完成即卸载。原始文件全部保留，只有UUID匹配且完成标记有效的记录才解码。EFI文本还会与现有环形解码器逐字节核对。

自构建 XNU 优先使用 KDP 保留现场，避免仅用定时复位判断路径。
当前 UEFI 页表/PAC 探针不是 XNU，不能通过内核 KDP 调试。

## 已有配置与实际阻断

配套 25F71 源码的 `config/MASTER.arm64.MacOSX` 已将 `mach_kdp`、`config_serial_kdp`、
`kdp_interactive_debugging` 放入 PERF_DBG_BASE；SHENG 没有移除它们。
Actions 39937165999 的实际归档包含 `kdp_raise_exception`、`kdp_register_send_receive`、
`kdp_serial_send` 和 `kdp_serial_receive`，编译参数保留 `-g`，优化为 `-O2`。
无需为这些已有选项重复构建。

Actions 39946670153 已链接 macOS 26.5 SHENG 可执行内核并生成对应 dSYM。
初版 QEMU 地址断点受到加载器错误映射影响，该通过结论已撤回。
修正 32 MiB VA/PA 同余后，现场指令与文件一致，实际进入 C panic；尚未到达 BSD。
sheng 实机内核调试传输仍未接通。
现有 `pe_serial.c` 只有被条件选择的平台后端，SHENG 尚未注册可用的收发实现。
仅添加 `kdp_match_name=serial` 不会自动得到 USB、网络或 UART 通道。

源码链路：`kdp_init` 注册串行收发；`kdp_serial_send/receive` 经 `pal_serial_*` 调用 `serial_putc/getc`。
网络后端通过 `kdp_register_send_receive` 提供直接收发，调试停机时必须能轮询工作，不能依赖已停止的调度器或中断。
fastboot 由 ABL 提供，ADB 由 Android 提供，两者都不是 XNU KDP 的现成传输。

## 接入验收

先完成一个实机可用的双向轮询后端，再配置启动时停机及 panic 等待。
具备后端后，按配套 XNU README 的 `debug=0x14e` 作为 panic 等待调试器起点；
需要启动时停住时加 DB_HALT 位，即 `debug=0x14f`。不同时添加强制重启位。
串行后端使用 `kdp_match_name=serial`；网络后端需填写真实接口名，不能虚构 en0。

每次调试保留同一次链接的未剥离内核、dSYM、UUID、链接 map、加载地址和 slide，不能拿原版 T8103 KDK 符号代替 SHENG 自构建符号。
传输未实现前，这些启动参数只作为待接入配置，不写入当前实机测试镜像。
验收以读取 PC/SP/寄存器、获取回溯并恢复执行为准；停止画面或归档中的 KDP 符号不等于已连接。

## arm64e 范围

arm64e 是包含指针认证约定的 ABI，不是仅内核态的一组指令。
EL0 程序可执行 PAC/AUT，内核负责密钥生命周期和特权状态；Apple 专有密钥行为另行处理。
本项目 Android EL0 的 PAC 往返已有实机证据；启动核 EL1 五类密钥库切换和恢复也已实测通过（flags=0x7fff）。
两项实验均不证明 Apple 的密钥派生和 XNU 任务生命周期已接通。
后续兼容同时覆盖用户态签名指针、dyld fixup、进程/线程切换、异常进入和用户返回。
不能只在内核替换指令，或通过放行 arm64e subtype 代替密钥语义实现。

来源：[配套 XNU 调试说明](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/README.md#debugging-xnu)、
[KDP 传输实现](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/kdp/kdp_udp.c)、
[Apple 用户态指针认证](https://developer.apple.com/documentation/security/preparing-your-app-to-work-with-pointer-authentication)、
[Clang arm64e ABI](https://clang.llvm.org/docs/PointerAuthentication.html)。

## 原生内核日志

参考 Snapintosh 固定源码的 `probes/xnuboot/telemetry.c`、`compat/console-link.h` 和
`tools/recover-console-log.py`。它由 EL2 监控层统一接收 SPTM SERIAL_PUTC 与 UART 输出，
保留开头和尾部，通过 q1n1 USB NCM / call service 导出。sheng 的原生 EL1 路线没有这层常驻服务，
不能只加 serial=3 就宣称获得 USB 日志。

`platform/sheng/macos26/log/retained_log.h` 在内核自己的映射和内存窗口中保留日志，
不用未确认归属的固定物理地址。头部 128 字节，启动前缀 16 KiB，尾部环形区 64 KiB。
`_sheng_log_buffer` 是同次链接中的地址来源，头部记录实际物理地址和内核 LC_UUID。
写入不等待锁；重入丢失单独计数，数据和提交游标清理到一致点。
视频与串行字符出口都接入，串行字符不重复记录；panic 的公共入口在串行初始化前也保存有界的格式化消息。
头部另保存 panic caller/SP、ELR_EL1、ESR_EL1、FAR_EL1 和 MPIDR_EL1。
这些是日志钩子执行时的寄存器，不能当成原始异常的完整现场；完整调试仍需 KDP 或 GDB。

`observe_macos26_kernel.py` 复用 UniXNU 的 UEFI/QEMU 入口和 GDB 传输，
按新内核符号停止后读取固定大小的日志，保存 `console.bin`、`console.txt`、`console.json`，
同时保留完整 GDB 寄存器和 UART 文件。`decode_native_log.py` 拒绝错 UUID、未知布局和截断输入，
明确标记环形覆盖、重入丢失与未完成写入，不把不完整日志当成完整记录。
构建同时保留实际内核、dSYM 和链接 map。

实机导出仍需实现并验证：原生 XNU 尚无 q1n1 NCM 等价后端；现有 Linux RAM reader 固定读取的是旧 UEFI 区域，
不能拿它读取新内核日志。若采用 warm reset 后的只读导出，必须把实际日志物理区传给 reader、
从 reader 的 Linux 分配器保留该区，并先验证 ABL/固件跨重启未覆盖它。
冷启动与断电不保留 RAM。当前不宣称跨重启保留或实机 USB 日志已通过。

来源：[Snapintosh USB NCM 启动与日志通道](https://github.com/Acelogic/Snapintosh/blob/main/README.md)、
[统一控制台缓冲区](https://github.com/Acelogic/Snapintosh/blob/2c60b47a950f6d98caed6b2551adc227f8ced4c9/probes/xnuboot/telemetry.c)、
[保留日志恢复](https://github.com/Acelogic/Snapintosh/blob/2c60b47a950f6d98caed6b2551adc227f8ced4c9/tools/recover-console-log.py)。

首次 EL1 同步异常还在 `locore.s` 的两类 EL1 long vector 入口保存一次硬件 ELR/ESR/FAR 和来源栈，
位置在依赖 current_thread 的原向量代码之前，避免早期 BRK 后的递归异常覆盖原因。
不改变原异常处理方向，不在这里复位；panic_state=3 表示这份首次异常现场，后续 panic 不覆盖它。
这段汇编和新增 reader 尚待目标构建及实机验收。

原生只读 reader 的独立源码为 `probes/native_log_reader.c`，构建器为 `scripts/build_native_log_reader.py`。
它按观察到的 DarwinBoot PA 和对应 `_sheng_log_buffer` 偏移计算范围，保留 96 KiB RAM，导出其中 82048 字节。
源内核内建 UFS，因此 reader 的 DT 显式禁用 `/soc@0/ufshc@1d84000`，不只依赖 PID1 不打开块设备。
USB 文件为 `NATIVLOG.BIN` 和 `STATUS.TXT`；`scripts/capture_native_log.py` 校验地址、长度和 CRC 后匹配内核 UUID。
失败也保留原始快照。相同内核 UUID 本身不证明数据来自当前一次启动，捕获记录始终单独标记 freshness/retention 未验收。

```sh
python3 scripts/build_native_log_reader.py --kernel-build <Actions产物中的macos26-xnu目录> \
  --kernel-physical-base <本次sheng屏幕实际显示的DarwinBoot内核PA> \
  --boot-template <当前槽boot备份>
python3 scripts/capture_native_log.py --reader-build <新reader的build.json> --output <新捕获目录>
```

这些工具只生成或读取候选产物，不自动重启、部署或刷写设备。

原生日志首次实际执行结果：Actions 39951693129 的内核在 QEMU 产生 6852 字节日志，解码 UUID 匹配，busy/覆盖丢失均为 0。
首次 EL1 同步异常头的 panic_state=3，PC 对应 crypto_random_kmem_ctx_size，FAR=0x150；后续 panic 保留该现场。
这验证了字符记录和首次异常记录的运行路径，尚不证明 sheng 跨重启 RAM 保留或 USB 导出成立。

实际候选封装命令：

```sh
python3 scripts/package_macos26_kernel.py --kernel-build <macos26-sheng-kernel产物目录> \
  --firmware-build out/firmware-build.json --backup-dir <当前槽备份目录>
```

封装使用当前厂商 DTB、32 MiB 同余加载器和 256 字节启动熵，不自动部署。

DarwinBoot 现在可为 `--panic-log` 设备树在 owned window 内分配独立 512 KiB，并填写 `/pram/reg`。
`/chosen/embedded-panic-log-size` 沿用 XNU 原接口；不使用厂商固定保留地址或未分配内存。
QEMU 实测 gPanicBase=0xfffffe000a000000、gPanicSize=0x80000，标准 panic 流程已产生完整寄存器、内核 UUID、回溯和压缩 stackshot。
已取回 512 KiB 原始 panic 区；version=8、CRC 匹配、内核 UUID 匹配，panic 文本 3500 字节、stackshot 2314 字节。
这是 QEMU 运行结果，未验收 sheng 重启后的保留或 USB 导出。

观察器增加 `--capture-panic-buffer`：从现场 gPanicBase 指针分块读取，保存 `xnu-panic.bin`、`xnu-panic.txt`、`xnu-stackshot.bin` 和元数据。
`scripts/decode_xnu_panic.py` 按配套源码的 packed version-8 头解码；范围损坏、UUID 不匹配或 CRC 未完成时保留原始区并明确标记。

reader v2 可同时导出原生控制台和标准 panic 区。
构建时增加 `--panic-physical-base <本次DarwinBoot打印的panic RAM PA>`，两段 RAM 分别保留并禁止 Linux 映射分配。
地址必须在实际 owned window 内，不能相互重叠；不用模拟器地址生成实机 reader。
USB 仍为 1 MiB 只读 RAM 磁盘，新增 `XNUPANIC.BIN`；每段有独立的映射状态和传输 CRC。
捕获器保留原始区，再按匹配内核解码 panic 文本和 stackshot。
ARM64 PID1 编译和包含真实 QEMU panic 的 FAT 导出/提取已通过；这些结果不代替实机 USB、重启后 RAM 保留的验收。
