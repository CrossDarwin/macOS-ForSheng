# macOS 26 原生安全组件

当前实际阻断是 `kern_trustcache.c:584: image4 interface not available`。
39973422068 的 ARM64E 内核在 QEMU 完成完整 corecrypto POST 后到达这里，尚未进入 BSD。
完整 panic、回溯和 stackshot 已保存于 `out/macos26-arm64e-39973422068/`。
字符环形日志已保留完整 panic 文字；标准 panic 区另保留寄存器、回溯和压缩 stackshot。
这些是 QEMU 结果。sheng实机已确认ARM64E启动汇编及早期C阶段0–F，执行到arm_vm_init调用前；corecrypto、Image4和BSD入口尚未实机确认。

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

当前内核已启用 ARM64E/HAS_APPLE_PAC，并扩展原始链式处理代码支持独立 MH_EXECUTE 的格式 7。
QEMU 已执行 116829 个指针修复，其中 43757 个需要认证；没有删掉认证位。
这解决了原生内核自身的启动指针，尚未实现原组件的 fileset 布局、外部符号重定位和注册时序。
本 BootKC 的指针格式为 8，步长为四字节；实际存在跨页的八字节指针槽，不能照搬 AuxKC 检查中更窄的边界假设。

## 下一段实现契约

继续使用已运行的原生 ARM64E 内核，构造原组件的 fileset 布局与重定位，再让真实初始化器注册接口。
DarwinBoot 当前只加载 MH_EXECUTE，不能将匹配 BootKC 当作已经可执行的原生候选。
函数回调、C++ 虚表和原组件 ABI 仍需在真实模块初始化时验证。
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

## 外部进度截图的后续线索

用户补充的截图声称使用 XNU 12377 与 macOS 26.5 原版 kext 到达 launchd，没有对应源码或日志。
以下只作为后续兼容项，不视为本项目已通过：

- IOBlockStorageDevice 的宏分支影响虚表；除 XNU_TARGET_OS_OSX 外，还需对照 TARGET_OS_OSX，逐槽核对原版 ABI
- 原版 kext 的 kalloc 类型信息可能包含真实签名，应按实际类型区分 KT_DATA_ONLY，不能统一当作数据指针
- 用户空间的 16 KiB 签名页需要匹配真实 CodeDirectory，不能仅按内核 4 KiB 验证单位切分
- 截图使用 rootauth=0 暂时跳过 sealed root 验证；本项目尚未推进到根卷挂载，不据此提前修改根认证

截图中的 NativeVirtioBlock 是 QEMU virtio-mmio 存储路径，不能直接当作 sheng 的 UFS 实现。
