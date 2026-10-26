# PAC 与原生安全组件

本项目使用配套 25F71 ARM64E 组件，并在自构建 SHENG EL1 内核中完成加载、重定位和初始化。
本页说明输入配对、认证指针和模块初始化方式，运行结果见[移植状态](status.md)。

## PAC 处理范围

签名和认证由 ARM 的 PAC/AUT 指令执行，密钥状态通过 EL1 密钥寄存器管理。
ARM64E 的兼容范围包括 EL0、EL1、签名指针及密钥生命周期。

映像生成器保留认证指针的 key、diversity 和 addrDiv，重建格式 7 链，由内核按实际地址签名。
内核函数回调、组件初始化器和 C++ 虚表继续使用各自认证约定，不统一清除认证位。
EL0 返回和进程切换使用原生密钥接入，不调用 VMAPPLE 的宿主 HVC 密钥服务。

启动核的密钥访问、保存和恢复已有实机独立证据；原版 dyld、launchd 和恢复服务也已执行。
这些结果仅覆盖当前运行路径，不代表全部 Apple 密钥派生语义或每种进程生命周期已验收。

## 配套输入与重定位

组件来自 `config/macos26.json` 固定的 25F71 M1 BootKC。
原始内嵌 XNU UUID 为 `DA4C776A-B10A-38B6-997B-BD66671C5D52`，与 SHENG 自构建 UUID 分开记录。
依赖闭包、组件集合、地址映射和完整哈希参与产物身份，不能换用其他系统版本的组件。

`scripts/emit_macos26_security.py` 生成实验映像，处理组件指针链、外部分支、内嵌头、kmod 和预链接元数据。
它保留内核代码地址及对应 dSYM；组件集合另有 KCID 和哈希。
生成器要求显式传入 `--qemu-only`，产物在此阶段保持实验状态。后续硬件封装另行核对观察记录。
不能把生成成功当作模块 ABI 或实机运行通过。

## 初始化顺序

原版 corecrypto 完成 POST 并注册实际函数表后，Image4、AMFI 和 CoreEntitlements 注册真实接口。
IOKit 与早期启动入口共享同一模块初始化结果，避免重复注册。
AMFI 使用配套组件中实际的安全策略入口；Image4 沿用正常 start，不额外重复注册接口。
pthread 通过配套组件的 `pthread_kext_register` 注册真实函数表，再执行内核线程初始化。

具体重定位数量、旧失败现场及逐轮修正保存在[历史组件调查](history/macos26-security-20261026.md)。

参考：[Clang 指针认证约定](https://clang.llvm.org/docs/PointerAuthentication.html)、
[Apple 用户态指针认证](https://developer.apple.com/documentation/security/preparing-your-app-to-work-with-pointer-authentication)。
