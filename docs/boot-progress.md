# 启动进度与日志

`sheng-boot-progress=1`开启独立底部诊断区，默认关闭，要求`cpus=1`。
示例：

```text
BOOT [#####-#---] - WindowServer exec
No new stage/service: 60s - no loop verdict
WindowServer pid=85 starts=2 exits=1 wait-status=256
LOG committed gen=73 bytes=59551 drops=0 error=0 lost=0
```

每个格子只表示对应事件曾实际到达，位置固定，不是百分比。
中间的`-`表示该事件尚未观察到；后面的事件可能先出现，不补齐未发生的格子。

| 格子 | 事件与边界 |
| --- | --- |
| 0 | 原生内核已进入控制台创建路径 |
| 1 | 已经过VM初始化，到达控制台创建路径 |
| 2 | 进入PE_lockdown_iokit，尚不表示IOKit全部服务已启动 |
| 3 | vfs_mountroot实际返回成功 |
| 4 | launchd映像已装载，不等于main或服务初始化完成 |
| 5 | recoveryosd或RecoveryOS Agent映像已装载 |
| 6 | WindowServer映像已装载，不等于显示连接成功 |
| 7 | 原版帧缓冲队列完成开屏通知 |
| 8 | 第一次交换请求已进入驱动验证路径，不等于呈现成功 |
| 9 | 驱动已完成第一帧CPU复制及写入屏障，不等于语言选择器内容已验收 |

新格子或首次观察到的目标服务更新停留时间。重复阶段、同一服务重新执行和普通刷屏均不重置。
日志记录目标服务的映像装载、退出、PID和原始wait status，底部显示最近目标服务。
计数范围是本次启动内观察到的目标服务；旧PID退出不会覆盖新PID的显示状态。
目标包括launchd、recoveryosd、RecoveryOS Agent、WindowServer、Language Chooser、
Recovery Springboard、lsd、coreservicesd、loginwindow和diskarbitrationd。

独立内核线程每2秒刷新，持久日志最多每30秒补一份停留摘要，新阶段立即记录。
计时器在根卷成功挂载后启动；此之前若停止，格子保留，但秒数不保证继续刷新。
定时线程无法获得CPU或内核整体停止时，显示也会停止，不能把静止画面单独判定为死循环。
早期时钟尚未初始化时返回0，不执行未就绪的时间换算。

底部使用已映射panic区中未使用的四行，与滚动日志区分开。
实际panic可以覆盖该区域并保留错误文本。第一次图形帧复制接管后停止诊断像素写入，
首次复制失败会恢复诊断区所有权，防止因错误路径永久隐藏面板。
每条像素扫描线短暂屏蔽中断并复查所有权，避免单核抢占后旧诊断写入覆盖图形帧。
日志和服务事件仍可继续保存。

`LOG`显示日志工作线程状态：off、opening、verified、committed或stopped。
`gen`只在实际提交后更新，`bytes`和`drops`来自保留环形日志。
`error`为存储错误值，`lost`记录未能取得诊断状态写入锁的事件。
存储写入没有成功时不会显示committed；该字段不能证明最后时刻或整个运行历史已保存。
日志文件仍使用现有两个预分配槽，不改GPT、FAT或其他文件。

封装的`--boot-progress`同时开启有界WindowServer stdout/stderr采集。
普通write和writev均记录尝试输出，每次最多159字节、最多检查16个iovec，超过上限标注截断。
用户地址读取失败时忽略该次诊断，原写入参数、UIO游标、错误和返回值保持原行为。
统一日志数据库、任意进程输出、完整历史和最终panic不在这项采集保证内。

主机测试覆盖重复事件、退出重启、旧PID、时间倒退和有界格式化。
独立ARM64 QEMU测试验证实际字体像素、停留时间、panic优先和诊断像素交接。
这些测试不等于配套完整内核或sheng实测，后两项另行记录。
