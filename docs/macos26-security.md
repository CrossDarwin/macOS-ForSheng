# macOS 26 原生安全组件

当前实际阻断是 `kern_trustcache.c:584: image4 interface not available`。
39961597801 的内核在 QEMU 完成完整 corecrypto POST 后到达这里，尚未进入 BSD。
完整 panic、回溯和 stackshot 已保存于 `out/macos26-panic-flush-39961597801/`。
字符环形日志与标准 panic 区分别导出；字符日志只有 panic 摘要，完整内容以独立 panic 区为准。

## 匹配输入与加载范围

输入是现有 25F71 M1 BootKC，不重新下载 IPSW。
内嵌 XNU UUID 必须为 `DA4C776A-B10A-38B6-997B-BD66671C5D52`。
按其实际 `OSBundleLibraries` 递归得到六个代码模块，另有七个内核 KPI 接口：

| 模块 | 链式指针 | 其中需要认证 |
| --- | ---: | ---: |
| AppleImage4 | 3813 | 2059 |
| AppleMobileFileIntegrity | 4134 | 1564 |
| CoreTrust | 418 | 79 |
| corecrypto | 1639 | 776 |
| IOCryptoAcceleratorFamily | 1118 | 1089 |
| CoreAnalyticsFamily | 1555 | 1503 |

总计 12677 个链式指针，其中 7070 个使用 IA 或 DA 密钥。
这些模块的内核指针目标均有同名原生导出候选。符号存在不证明函数、对象或回调 ABI 相同。
corecrypto 线性扫描中的两个未解析 B 候选来自内嵌 SHA-256 常量表，不是缺失的内核调用。
不能直接把线性指令扫描结果当作重定位表。

只读分析命令：

```sh
python3 scripts/inspect_macos26_security.py \
  --kernel-build private/ci/macos26-kernel-39958185731 \
  --output out/macos26-security/4636503.json
```

报告保留认证指针的 key、diversity、addrDiv，并列出外部指针和待审阅的分支候选。
脚本不修改 Apple 输入，不生成可执行候选，不把符号匹配标为 ABI 通过。

## 上游可复用部分

UniXNU 的 `kits/NativePrelink/native_prelink.py` 只接受普通 ARM64、MH_EXECUTE 和旧 prelink 指针表。
其 `emit_prelink.py` 与 `xnu-10063.141.1-security-init.patch` 提供依赖闭包、原组件启动及 MAC 锁定前初始化的参考。
这套加载格式不能直接用于当前 ARM64E MH_FILESET。

Snapintosh 的 `probes/auxkc.py` 保留链式指针，由 XNU 的 `kernel_collection_slide` 完成认证签名。
其 `tools/kc-load.py` 则为监控层准备无 PAC 的指针，再由监控层重签。
sheng 当前没有该监控层，不能照搬后一条路径。

匹配 XNU 的 `osfmk/mach/dyld_kernel_fixups.h` 在未启用 HAS_APPLE_PAC 时，遇到认证指针会停止并报告 `Unexpected authenticated fixup`。
仅把模块放进 AuxKC，仍会留下未完成的链式重定位。
本 BootKC 的指针格式为 8，步长为四字节；实际存在跨页的八字节指针槽，不能照搬 AuxKC 检查中更窄的边界假设。

## 下一段实现契约

先解决原生内核与原组件的 ARM64E 边界，再让真实初始化器注册接口。
当前普通 ARM64 内核不具备原组件所需的认证回调和 C++ 虚表契约。
不能靠删掉指针认证位、补空函数表或略过 trust_cache_init 推进。

AppleImage4 的原始 `_kmod_link_init` 位于 `0xfffffe0009458e70`，调用 `_img4_interface_register`。
实际传入表为 `0xfffffe00080b4780`，版本 20，与匹配 XNU 的 IMG4_INTERFACE_VERSION 一致。
这些地址只描述此固定输入，不作为通用偏移使用。
原 `__mod_init_func` 指向两个 C++ 构造器；它们不是 `_kmod_link_init` 的替代入口。
AMFI 同样需要真实初始化，并注册 AMFI 与 CoreEntitlements 接口。

原生 PAC 实现必须覆盖引导密钥状态、链式指针签名、函数回调、C++ 虚表，以及随后 EL0/EL1 和任务切换的密钥生命周期。
VMAPPLE 的 HVC 密钥接口不能用于现有 sheng EL1 启动链。
公开 corecrypto 提供者的 POST 已通过，但不能据此替代原版 corecrypto 的全部导出及新版尾部接口。
每次实际接入后，用 QEMU 的原 panic 与对应符号定位下一处错误；实机部署不作为解决 ABI 缺口的手段。
