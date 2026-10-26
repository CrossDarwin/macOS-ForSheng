# 首次 panic 二维码

二维码把首次 panic 摘要绘制到已有帧缓冲的独立 panic 区，供手机离线扫码。
它用于补充磁盘快照来不及提交时的屏幕记录，不包含完整 RAM、完整日志或调用栈。

## 触发与布局

`sheng_log_panic()` 保存首次 panic 文本，并先显示文字，再尝试编码。
编码使用静态缓冲区和一次性原子占用，不申请内存、不等待锁、不写磁盘，也不发送网络请求。
重复或递归 panic 不替换首次消息。

左侧保留 `SHENG - PANIC DETAIL` 及自动换行文字，右侧显示黑白二维码。
二维码使用整数倍像素和四模块白色静区，最多占用诊断区宽度的一半。
编码失败或区域无法容纳至少两像素一个模块时，只显示文字。
普通滚动日志不能覆盖独立 panic 区；显示映射或内核本身损坏时仍可能无法绘制。

## 内容与边界

扫码结果是以 `SHENG-PANIC-1` 开头的文本，不是网页链接。

| 字段 | 含义 |
| --- | --- |
| `UUID` | 本次内核 LC_UUID，用于匹配符号 |
| `CALLER` | 首次 panic 传入的调用地址 |
| `SP`、`ELR`、`ESR`、`FAR` | panic 钩子执行时读取的寄存器 |
| `PHYS`、`IMAGE` | 保留日志记录的物理地址和内核映像虚拟地址 |
| `TOTAL`、`DROPPED` | 编码时日志的字符总量和 writer 忙时丢失字节数 |
| `REGS` | 固定为 `panic-hook`，区别于之前的 EL1 异常记录 |
| `REASON` | 最多 256 字节的原因摘要，非可打印 ASCII 转为空格 |
| `TRUNCATED` | 原因超过上限时为 `1`，否则为 `0` |

除 UUID 和说明字段外，数值字段均为 16 位十六进制，不带 `0x`。
总载荷缓冲区为 640 字节，二维码版本上限为 20，纠错等级为 M。
二维码中的寄存器不保证对应原始异常；完整回溯仍需要匹配符号和调试传输。

## 实现来源

设计参考 [Linux DRM panic](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_panic.c)
在崩溃路径使用有限资源绘制画面的方式。本项目不使用其压缩报告或网页解码格式。
编码器使用固定提交的 [Nayuki QR-Code-generator](https://github.com/nayuki/QR-Code-generator/tree/3c6d0b3cefb4e049dc337e82237c9644399716a8/c)，
原始 MIT 声明保留在源码中，提交与哈希记录于 `config/macos26-panic-qr.json`。
构建器只替换 libc 和断言依赖，生成不依赖内存分配器的内核头文件。

## 验证

独立 ARM64 QEMU 测试执行实际 panic 绘制路径，再从帧缓冲像素解码二维码，逐字节比较载荷。
同一测试覆盖普通 writer 忙、此前存在可恢复异常、长消息截断、重复 panic 和后续滚动输出。
完整 XNU 及配套驱动已在构建 40326900585 编译通过；该结果不等于 sheng 实机扫码已通过。
后续结果记录在[移植状态](status.md)。

测试需要已准备的 XNU 字体、ARM64 clang/LLD 和 QEMU。指定 `CLANG` 后，在仓库根目录运行：

```sh
uv pip install --python .venv/bin/python -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -p test_native_panic_panel.py
```
