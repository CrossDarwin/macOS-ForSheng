# sheng 内核现场与 KDP

自构建 XNU 优先使用 KDP 保留现场，避免仅用定时复位判断路径。
当前 UEFI 页表/PAC 探针不是 XNU，不能通过内核 KDP 调试。

## 已有配置与实际阻断

配套 25F71 源码的 `config/MASTER.arm64.MacOSX` 已将 `mach_kdp`、`config_serial_kdp`、
`kdp_interactive_debugging` 放入 PERF_DBG_BASE；SHENG 没有移除它们。
Actions 39937165999 的实际归档包含 `kdp_raise_exception`、`kdp_register_send_receive`、
`kdp_serial_send` 和 `kdp_serial_receive`，编译参数保留 `-g`，优化为 `-O2`。
无需为这些已有选项重复构建。

尚无 macOS 26 可执行内核、对应 dSYM 或 sheng 可用的内核调试传输。
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
