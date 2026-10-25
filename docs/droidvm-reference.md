# DroidVM参考与sheng接入顺序

核对时间：2026-10-25。参考源码固定为
[`Droid-VM/macOS-DroidVM@1dfb172`](https://github.com/Droid-VM/macOS-DroidVM/tree/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9)。
用户提供了该VM已显示界面的进展；本文记录实际读过的源码及适用条件，不将源码存在视为本项目实测通过。

sheng已在实机执行25F71原版launchd，并运行mount/apfs_boot_util。当前失败是
`mount-phase-1`缺少ISC/xART角色卷。正在验证OS只读窗口与ISC有限RAM写入层，尚未证明新方案在QEMU或实机完成挂载。

## 当前优先项

| 优先级 | 参考 | 实际行为 | sheng处理 |
| --- | --- | --- | --- |
| P0 | [mount替代入口](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/systemos-shims/sbin/mount) | `mount -P`返回成功，其余参数转发给mount.real；fsck替代入口也返回成功 | 只能与已完成的替代挂载链配套。当前先让实际ISC角色卷挂载成功，不能用退出码掩盖缺卷 |
| P1 | [SystemOS构造](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/scripts/make-macos-systemos.sh)与[Data种子](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/scripts/make-macos-data-seed.sh) | 从安装模板准备可写目录；只读资源留在SystemOS，通过链接连接Data；补充/var、/etc、/tmp | 完整系统阶段复用目录依赖分析。路径、权限、大小和UUID须从25F71实际输入重新取得；当前BaseSystem恢复环境不替换为它的完整系统布局 |
| P1 | [启动与退出诊断](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/droidvm/README.md) | 提供exec/exit、致命异常回溯及受参数控制的stackshot | 后续服务失败时保留进程、退出原因和调用错误。继续使用sheng现有保留日志与独立屏幕区；VM的PL011串口不能当作实机日志通道 |
| P2 | [kqworkloop限制修正](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/patches/xnu-12377/0005-no-kqworkloop-limits-launchd-sets-3-10-daemons-need-.patch) | 将动态workloop软硬上限设为无限制，针对其opendirectoryd失败 | 先记录sheng实际服务退出及限制值。只有出现同因失败才做局部开发开关；现在不取消全局限制 |
| P2 | [DroidVMDisplay](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/kext/DroidVMDisplay/DroidVMDisplay.cpp) | 接IOMobileFramebuffer交换队列，CPU复制IOSurface到启动帧缓冲，并处理交换完成；代码另有27与26.5的交换记录适配 | 用户态持续运行后，优先参考提交、VBL和完成通知契约。使用25F71对应接口，单独验证sheng物理帧缓冲映射、步长和缓存属性 |
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

1. 用新内核在QEMU的生产NativeUfsBlock路径发布ISC，挂载xART、Preboot和Hardware，并继续执行原版launchd。
   底层读取由离线镜像替身提供，不能据此宣称物理UFS仿真通过。
2. 确认RAM写入层无失败、驻留数据不超过64MiB。该层重启即丢失，不代表SEP可信存储。
3. 仅在已有64GiB macosroot内部追加ISC种子，回读后提交清单。保留GPT、Android userdata和现有BaseSystem字节。
4. 实机越过当前挂载失败后，再按实际失败服务补目录与用户态接口。持续用户态通过后接显示提交与输入，最后验证GPU后端。
