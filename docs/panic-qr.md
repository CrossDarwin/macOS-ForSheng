# 首次 panic 二维码

首次 panic 二维码将内核身份、调用地址和有界错误摘要绘制到独立 panic 区，供手机离线读取。
该记录用于补充崩溃时尚未提交的磁盘日志，不包含完整 RAM、调用栈或无限日志。

## 生成流程

`sheng_log_panic()` 按以下顺序处理首次消息：

1. 占用首次 panic 文本缓冲区，最多保存 4,095 字节。
2. 发布并绘制文字面板，使二维码编码失败时仍有可读消息。
3. 单独读取 panic 钩子寄存器，准备有界文本载荷。
4. 使用静态缓冲区编码二维码，完成后重新绘制独立 panic 区。

panic 接管后拒绝新的 GOP 和诊断写屏。XNU 停住其他核后重绘，最终停机入口再次重绘，覆盖最后一条在途扫描线。
绘制不等待普通写屏锁。

首次消息使用一次性原子状态管理。重复或递归 panic 不替换已保存的文本和二维码。
编码与绘制路径不申请内存、不等待锁、不写磁盘，也不发送网络请求。
普通日志 writer 与首次 panic 缓冲区分开管理，writer 忙时仍可保存首次文本。

## 屏幕布局

左侧显示 `SHENG - PANIC DETAIL` 及自动换行文本，右侧显示二维码。
二维码最多占用诊断区宽度的一半，使用整数倍像素，四周保留四模块白色静区。
编码失败或显示区域无法容纳每模块至少两像素时，保留全宽文字布局。

二维码使用现有 panic 帧缓冲映射。普通滚动日志使用另一块区域；
若显示映射或内核执行状态本身损坏，文字和二维码都可能无法绘制。

## 载荷格式

扫码结果以 `SHENG-PANIC-1` 开头，后续各行使用 `字段=值` 格式，内容为离线文本。

| 字段 | 格式与含义 |
| --- | --- |
| `UUID` | 标准 UUID 字符串，本次内核的 LC_UUID |
| `CALLER` | 首次 panic 传入的调用地址 |
| `SP`、`ELR`、`ESR`、`FAR` | panic 钩子执行时的寄存器 |
| `PHYS`、`IMAGE` | 保留日志的物理地址、内核映像虚拟地址 |
| `TOTAL`、`DROPPED` | 编码时已记录字节总量、字符 writer 忙时丢失的字节数 |
| `REGS` | 固定值 `panic-hook` |
| `REASON` | 最多 256 字节的原因摘要，非可打印 ASCII 替换为空格 |
| `TRUNCATED` | 原因超出摘要上限时为 `1`，否则为 `0` |

地址、寄存器和字节计数字段使用 16 位十六进制，不带 `0x`。
总载荷缓冲区为 640 字节，二维码版本上限为 20，纠错等级为 M。

`REGS=panic-hook` 表示寄存器来自本次 panic 钩子，而非 RAM 头中此前保存的 EL1 同步异常。
这些值仍可能与触发原始故障时的寄存器不同。符号解析需使用同次内核的 UUID、dSYM 和加载地址。

## 运行测试

在仓库根目录执行测试。环境需具备 LLVM 的 clang、LLD 和 llvm-nm，以及以下已准备文件：

| 路径 | 内容 |
| --- | --- |
| `sources/macos26/xnu/osfmk/console/iso_font.c` | 配套 XNU 字体 |
| `out/qemu-root/usr/bin/qemu-system-aarch64` | 支持测试目标的 QEMU |
| `out/qemu-root/usr/lib/x86_64-linux-gnu/` | 该 QEMU 的动态运行库 |

1. 安装像素读取和二维码解码依赖：

   ```sh
   uv pip install --python .venv/bin/python -r requirements-test.txt
   ```

2. 将编译器路径替换为本地 LLVM 路径后运行：

   ```sh
   CLANG=/path/to/llvm/bin/clang \
     .venv/bin/python -m unittest discover -s tests -p test_native_panic_panel.py
   ```

测试在 ARM64 QEMU 中执行实际绘制代码，再从像素解码二维码并比较载荷。
它还检查长消息截断、此前存在可恢复异常、重复 panic 和普通日志后续写入。
输出保存在 `out/native-panic-writer-validation/`。测试被跳过时，没有产生新的执行验证。
构建和实机读取结果见[移植状态](status.md)。

构建 40332670337 的 sheng 实机已完整读出首次 panic 二维码，内核 UUID 为
`D8D9EDA4-EC94-3EBB-A60F-FD64D818760F`，`TRUNCATED=0`。
本次摘要包含 WindowServer 保存的用户态对齐异常；磁盘周期快照未包含该次最后停机。
此结果确认该次实机显示和扫码链路，不保证其他崩溃都能完成绘制。

## 来源

崩溃路径的绘制方式参考 [Linux DRM panic](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_panic.c)。
本实现使用离线摘要，不接入 Linux 的压缩报告或网页解码格式。
编码器来自固定提交的 [Nayuki QR-Code-generator](https://github.com/nayuki/QR-Code-generator/tree/3c6d0b3cefb4e049dc337e82237c9644399716a8/c)。
原始 MIT 声明保留在源码中，提交和哈希由 `config/macos26-panic-qr.json` 固定。
`scripts/native_panic_qr.py` 替换 libc 和断言依赖，生成内核使用的头文件。
