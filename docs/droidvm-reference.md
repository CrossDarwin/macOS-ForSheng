# DroidVM参考与sheng接入顺序

## 2026-10-26桌面路径复核

本次直接核对固定提交
[`031c35a`](https://github.com/Droid-VM/macOS-DroidVM/tree/031c35a57c89946977e51a1d64e009062faaed19)，
上游main当时也位于该提交。下面区分实际采用、待接入和完整系统阶段使用的机制。

| 机制 | 上游实际实现 | sheng当前处理 |
| --- | --- | --- |
| 系统与Data布局 | [SystemOS](https://github.com/Droid-VM/macOS-DroidVM/blob/031c35a57c89946977e51a1d64e009062faaed19/scripts/make-macos-systemos.sh)承载只读资源，[Data种子](https://github.com/Droid-VM/macOS-DroidVM/blob/031c35a57c89946977e51a1d64e009062faaed19/scripts/make-macos-data-seed.sh)从安装模板创建可写目录与链接 | 当前BaseSystem已运行自身临时Data流程。完整系统阶段按25F71模板准备Data、firmlink目标和持久存储，复用其依赖梳理方式 |
| 进入登录会话 | [stage-gpu-plugin.py](https://github.com/Droid-VM/macOS-DroidVM/blob/031c35a57c89946977e51a1d64e009062faaed19/scripts/stage-gpu-plugin.py)支持.AppleSetupDone、SkipSetupItems、本地用户和按标签禁用服务 | 这是完整系统登录路线；当前图形Recovery继续验收原版Language Chooser与Recovery Springboard，后续安装系统再采用对应会话配置 |
| 持久Data身份 | [run-macos-vm.py](https://github.com/Droid-VM/macOS-DroidVM/blob/031c35a57c89946977e51a1d64e009062faaed19/scripts/run-macos-vm.py)有DataStore时移除ephemeral-storage，避免usermanagerd跳过persona manager | 对持久Data配置采用同一语义；当前ISC角色卷RAM写入层仍是临时存储，不伪称持久Data |
| 帧交换 | [DroidVMDisplay](https://github.com/Droid-VM/macOS-DroidVM/blob/031c35a57c89946977e51a1d64e009062faaed19/overlay/kext/DroidVMDisplay/DroidVMDisplay.cpp)从4个活动层选最大完整画面，避免登录过渡时复制小指针层 | 已接入有尺寸、比例和像素格式检查的4层选择。40301287790首次捕获800×600 BGRA第0层，实际选择正确；会话转换后的窗口显示仍待验 |
| CPU呈现 | 同一显示实现通过readBytes逐行读取IOSurface | 实际CPU栈确认逐行读取反复建立物理拷贝窗口，已改为每帧一次有界只读映射，失败回退逐行读取。40305570169的60次样本未再命中该窗口路径 |
| Metal发现与执行 | [NativeAdrenoMetalPlugin](https://github.com/Droid-VM/macOS-DroidVM/blob/031c35a57c89946977e51a1d64e009062faaed19/overlay/metal/NativeAdrenoMetalPlugin.mm)经IOGPUMetalDevice注册，连接NativeBridge、Turnip及GPU用户客户端 | 已核对发现、设备包装及对象状态契约。当前先完成软件Recovery；原生Adreno的内存、提交和同步仍需实际后端支持 |
| 用户态诊断 | [0009诊断补丁](https://github.com/Droid-VM/macOS-DroidVM/blob/031c35a57c89946977e51a1d64e009062faaed19/patches/xnu-12377/0009-bring-up-diagnostics-stderr-log-sc-trace-sample-pid-.patch)按参数镜像stdout/stderr并采样线程；stage脚本可运行log show、log stream及定时sample命令 | 当前QEMU有只读线程栈，macoslog已通过同候选两次提交读回。已接入默认关闭的进程输出镜像，支持stderr、stdout/stderr及精确进程名筛选，159字节以上明确标注截断。边界测试、配套编译及原版dyld/launchd实际输出已验证；统一日志采集仍待接入 |

本轮已通过RecoveryOS Agent的LaunchServices注册及Language Chooser蓝牙等待。
实际输入使简体中文选择保留，并让原版状态机从6进入4、随后进入8；Recovery Springboard进程已出现。
最后的只读栈为Springboard向WindowServer查询显示状态，WindowServer仍有软件合成工作；
未取得恢复工具窗口的显示证据，不能仅凭进程出现宣称窗口可用。
服务裁剪依据实际缺失硬件及重试/崩溃记录，沿用上游按标签集中配置的方式；
应用注册、显示服务、Data和日志服务仍保留，避免把必要依赖一并移除。

用户已明确本轮以语言选择器显示和输入为验收点，恢复工具窗口不再阻塞sheng测试。
封装接入同候选的显示源、UI页策略、6张原始截图、中文状态、真实输入事件和调试器写入审计。
实机只启用GOP和UI策略，不加入QEMU VirtIO输入节点；物理输入、GPU加速和恢复工具窗口均保留未通过状态。
QEMU运行与sheng实测、源码存在与实际通过分别记录。

构建40305570169实际运行中，原版语言列表与中文标题已显示，真实点击后只读字段为zh-Hans。
6张间隔8秒的原始QMP截图均保留标题、列表及中文选中行，未再发生此前观察到的局部空白。
该结论限定这段约40秒的静态观察；继续后的Recovery工具窗口尚未验收。
逐行读取对照的60次CPU样本中有28次落在物理拷贝窗口，新候选同样长度样本未再命中该路径；
这是短时执行位置对照，不等于完整启动耗时或实机性能验收。

参考上游workloop修正后，也读回了当前实际限额：WindowServer、Language Chooser、
RecoveryOS Agent、opendirectoryd的soft/hard均为0，数量分别为24、31、25、11。
配套源码只在限额大于0时检查超限，因此本轮不套用上游针对3/10限额的补丁。

按DroidVM诊断机制改写的进程输出镜像已在构建40307065705编译通过，并取得QEMU运行证据。
`sheng-stderr-log=1`镜像stderr，`=2`镜像stdout和stderr，默认0关闭；
`sheng-stderr-name=launchd`按内核进程短名精确筛选，不指定时记录所有进程。
原版dyld/launchd实际输出已出现带fd、PID和进程名的保留日志，测试中只观察到所选launchd的诊断行。
每次最多复制159字节并标注截断，读取失败不打印，原write/write_nocancel调用保持不变。
该入口不覆盖writev或统一日志数据库，不能称为完整用户态日志。
正式采集统一日志时仍需配套原版log show/log stream；实机与持续写盘链路尚未用此版本验收。

## 2026-10-26补充核对

另行核对[DroidVM 59659e4](https://github.com/Droid-VM/macOS-DroidVM/tree/59659e407eb25b77fabd1d3298337683340d1357)
及[Snapintosh 940eeb9](https://github.com/Snapintosh/Snapintosh/tree/940eeb95ba637528dc45ba098e6b8091163dd489)，
不替换此前已经配套验证的显示输入。
DroidVM的SystemOS/Data构造仍用于安装系统布局；当前25F71 BaseSystem恢复路线保留实际临时Data挂载。
其Metal插件需要真实IOGPU后端，不能只发布设备名称就当作渲染可用。

Snapintosh的[GUI路线](https://github.com/Snapintosh/Snapintosh/blob/940eeb95ba637528dc45ba098e6b8091163dd489/docs/GUI-BOOT-ROADMAP.md)
撤下未实现的设备，包括蓝牙；其Adreno X2显示、Metal驱动及编译器与sheng硬件不同。
当前复用的是按实际硬件能力选择原版缺失设备分支的做法。
QEMU已实际启动Language Chooser并由WindowServer显示苹果进度画面，
语言选择器在蓝牙初始化中等待，正在验证无控制器路径；语言列表和sheng图形Recovery均尚未通过。

以下保留此前固定提交的接入记录，不把上游状态或源码存在视为本项目运行证据。

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
| P0 | [Metal前端](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/metal/NativeAdrenoMetalPlugin.mm)与[GPU服务](https://github.com/Droid-VM/macOS-DroidVM/blob/1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9/overlay/kext/DroidVMGpuKext.cpp) | 连接IOGPU服务发现、Metal插件、NativeBridge和Turnip；部分未提供方法动态返回零 | 可参考插件发现与用户客户端接口。源码不能证明完整渲染正确或sheng物理Adreno可用；GPU后端、内存、提交、同步与显示各自验收 |

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


## 首帧调查：从Metal等待到软件合成目标

真实WindowServer异常栈已定位到WSSystemCanCompositeWithMetal的once block调用abort，
EXC_CRASH/SIGABRT与原版“No suitable Metal devices present after %llu seconds.”分支一致。
显示枚举、打开及开屏均已通过，尚无可用Metal设备及第一帧。
复制GOP scanout本身无法满足Metal设备发现。后续显式QEMU实验已越过该检查，
进入原版软件合成的显示更新，当前退出点改为IOSurface像素格式不受支持；尚无第一帧。

重新核对固定版本NativeAdrenoMetalPlugin：IOGPUMetalDevice负责插件加载，
实际设备由native_bridge_metal_open创建，并依赖Turnip及AGXAccelerator用户客户端。
其动态缺失方法返回零用于接口调查，不能作为sheng完整渲染实现。
原版25F71保留CompositorSW路径，下一项先验证原版软件合成入口及像素输出；
默认选择与阴影初始化都调用Metal能力检查，不能只改默认合成器选择。
QEMU实验让原版Metal检查的once block保留“无设备”结果，保留PAC签名和认证，
随后进入WSCompositeDestinationCreateWithIOSurface；该路径尚无帧输出，不能声称软件桌面可用。


## UniXNU显示与GPU参考

[GPU适配文档](https://unixnu.com/zh/porting/gpu)把A740电源/固件、
SMMU映射、命令/fence和Metal前端分开验收；不能把接口存在视为sheng硬件加速已通过。
[显示文档](https://unixnu.com/zh/porting/display)要求先确认CPU呈现的像素布局、行跨度、
缓冲大小和交换生命周期，再接GPU呈现。当前GOP软件路径采用这一验收顺序。

本地Snapintosh固定参考28663c30f0a14c1862c099d6ea46f1b3421ab011的
`gpu/adreno-kext/kext/src/AdrenoDisplay.cpp`明确用IOAV colorimetry=10声明sRGB，
避免Default RGB的16被识别为原生广色域，进而选择扩展颜色表面。
本项目GOP只公布8-bit SDR及sRGB色度，仍继承了16，声明不一致。
候选补丁改为10；保留IOSurface真实格式和存储布局，不伪造格式查询返回值。
单变量QEMU实验已确认改为sRGB后仍分配RGhA，不能据此宣称首帧阻断解除。
后续在分配器选择格式之前验证BGRA目标，GPU加速仍未验收。


后续显式QEMU实验已证实：让原版framebuffer_pixel_format在分配前选择BGRA后，
实际IOSurface为BGRA，原版软件合成能够到达完整GOP复制并将帧计数推进至1。
800×600画面只有黑底和鼠标指针，尚无Recovery窗口。
这条软件呈现路径仍包含QEMU客体代码修改；不能据此宣称原版配置、实机或GPU加速已通过。
