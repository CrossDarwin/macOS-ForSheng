# sheng 内核现场与 KDP

自构建 XNU 优先使用 KDP 保留现场，避免仅用定时复位判断路径。
当前 UEFI 页表/PAC 探针不是 XNU，不能通过内核 KDP 调试。

## 已有配置与实际阻断

配套 25F71 源码的 `config/MASTER.arm64.MacOSX` 已将 `mach_kdp`、`config_serial_kdp`、
`kdp_interactive_debugging` 放入 PERF_DBG_BASE；SHENG 没有移除它们。
Actions 39937165999 的实际归档包含 `kdp_raise_exception`、`kdp_register_send_receive`、
`kdp_serial_send` 和 `kdp_serial_receive`，编译参数保留 `-g`，优化为 `-O2`。
无需为这些已有选项重复构建。

Actions 39946670153 已链接 macOS 26.5 SHENG 可执行内核并生成对应 dSYM。
QEMU 的真实 UEFI 交接已到达 arm_init，16K / 47 位页表开启。sheng 实机内核调试传输仍未接通。
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
