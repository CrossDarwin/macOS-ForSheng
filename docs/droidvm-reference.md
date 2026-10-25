# DroidVM参考与sheng接入顺序

核对时间：2026-10-25。参考源码固定为
[`Droid-VM/macOS-DroidVM@1dfb172`](https://github.com/Droid-VM/macOS-DroidVM/tree/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9)。
用户提供了该VM已显示界面的进展；本文记录实际读过的源码及适用条件，不将源码存在视为本项目实测通过。

sheng已在QEMU和实机执行25F71原版launchd，挂载ISC三个角色卷并完成临时Data与模板复制。
实机运行时日志已写入macoslog并在重启后由Recovery读回。当前阻断是WindowServer反复exit(1)，
尚无图形Recovery。QEMU已确认缺少IOHIDSystem，并在加入配套IOHIDFamily后通过服务打开及共享内存初始化。
显示发现和提交尚未通过，实机具体失败调用仍待定位。

## 当前优先项

| 优先级 | 参考 | 实际行为 | sheng处理 |
| --- | --- | --- | --- |
| 已评估 | [mount替代入口](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/systemos-shims/sbin/mount) | `mount -P`返回成功，其余参数转发给mount.real；fsck替代入口也返回成功 | 只能与已完成的替代挂载链配套。ISC角色卷与临时Data现已实测通过，保留实际挂载链，不引入无条件成功 |
| P1 | [SystemOS构造](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/scripts/make-macos-systemos.sh)与[Data种子](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/scripts/make-macos-data-seed.sh) | 从安装模板准备可写目录；只读资源留在SystemOS，通过链接连接Data；补充/var、/etc、/tmp | 完整系统阶段复用目录依赖分析。路径、权限、大小和UUID须从25F71实际输入重新取得；当前BaseSystem恢复环境不替换为它的完整系统布局 |
| P0 | [启动与退出诊断](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/droidvm/README.md) | 提供exec/exit、致命异常回溯及受参数控制的stackshot | 已取得实机WindowServer退出码及重启记录，QEMU已用调用返回值确认并解除HID服务缺失。下一步取得显示发现和提交结果。继续使用保留日志、已实测的macoslog快照与独立屏幕区；VM的PL011串口不作为实机日志通道 |
| P2 | [kqworkloop限制修正](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/patches/xnu-12377/0005-no-kqworkloop-limits-launchd-sets-3-10-daemons-need-.patch) | 将动态workloop软硬上限设为无限制，针对其opendirectoryd失败 | 先记录sheng实际服务退出及限制值。只有出现同因失败才做局部开发开关；现在不取消全局限制 |
| P1 | [DroidVMDisplay](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/kext/DroidVMDisplay/DroidVMDisplay.cpp) | 接IOMobileFramebuffer交换队列，CPU复制IOSurface到启动帧缓冲，并处理交换完成；代码另有27与26.5的交换记录适配 | 用户态已持续运行，接下来参考服务发现、用户客户端打开、提交、VBL和完成通知契约。使用25F71对应接口，单独验证sheng物理帧缓冲映射、步长和缓存属性 |
| P3 | [Metal前端](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/metal/NativeAdrenoMetalPlugin.mm)与[GPU服务](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/kext/DroidVMGpuKext.cpp) | 连接IOGPU服务发现、Metal插件、NativeBridge和Turnip；部分未提供方法动态返回零 | 可参考插件发现与用户客户端接口。源码不能证明完整渲染正确或sheng物理Adreno可用；GPU后端、内存、提交、同步与显示各自验收 |

## 已确认不直接适用的补丁

- [Sandbox版本转换](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/patches/xnu-12377/0006-Sandbox-macOS-27-userland-vs-the-26.5-kext-ENOENT-EI.patch)
  明确处理27用户态与26.5 kext的调用差异，并有忽略错误的开发路径。sheng当前内核、组件和用户态配套25F71，不引入跨版本调用编号转换。
- [共享区域分页死锁修正](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/patches/xnu-12377/0008-shared-region-pager-release-the-source-page-before-g.patch)
  修复其4KiB内核为16KiB滑动页收集相邻页时的互等。sheng为16KiB内核，当前源码没有它新增的相邻页收集路径，不能直接套用。
- [owner链兼容代码](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/patches/xnu-12377/0002-owner-chain-scratch-page-before-the-mounts-default-D.patch)
  包含无条件允许设备及替代摘要的兼容实现。可参考提前准备挂载所需scratch页和按UUID找实际IOMedia的顺序，不能将这些返回成功的实现当作有效认证。
- VM的VirtIO/Gunyah设备、PL011和普通客体RAM显示缓存策略，不替代sheng的物理UFS、显示和中断实现。

## 执行门槛

1. ISC三个角色卷、64MiB有限RAM写入层、临时Data及模板复制已在QEMU和实机通过。
   ISC已追加到现有macosroot并完整回读，GPT、Android userdata及原BaseSystem未改变。
2. 运行时日志的两个持久快照槽已在实机写入并由Recovery读回；只保存前缀、尾部和丢失计数。
3. QEMU已通过配套IOHIDSystem查找、用户客户端打开和共享内存创建。接下来记录显示发现和提交，保持原版SkyLight错误判断。
   实机exit(1)不单独证明HID或显示的具体失败调用；没有同因证据时不跳过服务检查。
4. 显示服务和用户客户端建立后，再验证实际帧缓冲映射、交换完成及输入，最后验证GPU后端。

## 已实现的GOP接入与尚未通过的部分

显示源和ABI header按固定提交、完整哈希获取。增量补丁位于
platform/sheng/macos26/display/0001-native-gop-display.patch。
新类NativeGOPDisplay与UFS放在同一个board companion bundle，匹配类别和生命周期各自独立。
不发布AppleParavirtGPU服务，不转换27版swap记录；26.5内核、kext及用户空间保持配套。
物理GOP缓存属性、服务发现和交换完成均需运行证据，现阶段没有GPU加速资格。

原版25F71 IOMobileFramebuffer.framework在查询服务前，先枚举IODeviceTree:/arm-io的子节点，
按device_type为display-subsystem或ext-display-subsystem统计显示管线。
只有参考数量大于已枚举服务数量时才进入IOMobileFramebuffer匹配与等待路径。
因此可选--native-gop-display同时描述一个sheng,gop-framebuffer显示子系统，并开启默认关闭的驱动。
这描述启动帧缓冲的一个显示管线，不表示存在Apple DCP或虚拟GPU。
缺少arm-io、描述冲突或重复节点时拒绝生成；未开启选项时不新增显示节点。
实际框架是否完成服务匹配和主显示连接仍待QEMU验证。


QEMU中原版WindowServer已在枚举完成路径读到参考管线1、已枚举1、显示记录1。
NativeGOPDisplay实际启动800×600，用户态服务发现已通过。
下一项是原始显示客户端打开返回值及实际帧提交；尚未确认GUI或sheng物理显示。

同一候选的原版显示打开函数返回0、输出连接非空，输入记录为primary显示。
原版用户客户端路径已通过；仍需验证IOSurface复制、交换完成和画面内容。
