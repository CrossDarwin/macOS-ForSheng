# DroidVM 显示与用户态参考

本页说明固定版本 DroidVM 中已用于 sheng 移植的机制及不能直接复用的部分。
参考源码固定为 [031c35a](https://github.com/Droid-VM/macOS-DroidVM/tree/031c35a57c89946977e51a1d64e009062faaed19)，不将其后续主分支行为视为已核对。

## 已采用的机制

| 机制 | 本项目实现 | 验证边界 |
| --- | --- | --- |
| 显示服务 | 适配 DroidVMDisplay 的匹配、用户客户端及交换生命周期，发布实际 GOP 管线 | QEMU 原版显示框架已连接；sheng 已开屏 |
| 层选择 | 从活动层选择符合尺寸、比例和像素格式的完整画面 | QEMU 已选中 800×600 BGRA 图层 |
| CPU 呈现 | 对 IOSurface 做每帧一次有界只读映射，失败时回退逐行读取 | QEMU 已复制真实画面，不代表 GPU 加速 |
| 用户态诊断 | 按进程名有界镜像 write/writev 的尝试输出 | 已接入 WindowServer 诊断，范围见[日志进度说明](boot-progress.md) |
| 恢复环境 | 保留 BaseSystem 自身临时 Data 流程，提供实验 ISC 角色卷 | QEMU 与 sheng 均已有挂载和服务执行证据 |
| 虚拟输入 | 独立 VirtIO HID 实验驱动 | QEMU 可选择简体中文，不实现 sheng 触控 |

显示源、ABI 输入及原始许可分别由 `config/macos26-gop-reference.json` 和输入准备器固定。
驱动修改位于 `platform/sheng/macos26/display/`，第三方署名见[许可说明](../THIRD_PARTY_NOTICES.md)。

## 当前软件显示路径

25F71 的显示框架先枚举 `IODeviceTree:/arm-io` 中的显示子系统，再匹配 IOMobileFramebuffer。
开启原生 GOP 选项时，设备树描述一个实际启动帧缓冲管线，驱动使用其地址、尺寸和行跨度。
这不发布 Apple DCP 或 AppleParavirtGPU 身份。

原版 WindowServer 的软件合成路径仍会经过 Metal 能力检查。
当前实验策略保留“无 Metal 设备”的结果，使原版软件合成继续创建 IOSurface 目标，再由 GOP 驱动复制。
该策略不提供 Metal 设备、命令队列或 Adreno 加速。

QEMU 已显示原版语言选择器，并通过真实输入选中简体中文。
选择后 Recovery Springboard 进程已出现，但恢复工具窗口未验收。
sheng 最近到达开屏阶段后发生物理地址 panic，尚无语言选择器画面；具体候选见[当前状态](status.md)。

## 不能直接复用的部分

DroidVM 的 GPU 桥依赖宿主 NativeBridge、Turnip 及实际用户客户端。
只复制 Metal 插件或补齐方法名称，不能为原生 sheng 提供内存映射、命令提交和 fence 同步。
当前 CPU 画屏路径与之后的 Adreno 740 加速移植分开验收。

完整系统的 Data 种子、firmlink、本地用户及跳过 Setup Assistant 属于安装后登录路径，
不用于把尚未启动的 Recovery 伪装为桌面。当前先验证原版语言选择器。

参考：[DroidVMDisplay](https://github.com/Droid-VM/macOS-DroidVM/blob/031c35a57c89946977e51a1d64e009062faaed19/overlay/kext/DroidVMDisplay/DroidVMDisplay.cpp)、
[UniXNU 显示适配](https://unixnu.com/zh/porting/display)、[UniXNU GPU 适配](https://unixnu.com/zh/porting/gpu)。
早期 Metal 等待、像素格式和会话调查保存在[历史记录](history/droidvm-reference-20261026.md)。
