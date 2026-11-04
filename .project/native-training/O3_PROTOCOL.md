# O3 球历史连续环形缓冲候选

2026-10-15，候选实施前登记。

主负载：1 controlled player / cadence10 / 预设动作；其余七组为回退检查。
同一隔离 Release 编译器，CPU 固定为最小可用 CPU，1024 transitions，8 组交错配对。
先完成当前源码 gprofng 16384-step 样本；原 .so/core 和完整 manifest 保存在
`/tmp/football-o3-baseline-20261015-a`，候选覆盖构建前保留。

候选使用已有 Boost 的 circular_buffer，容量 1001：正常历史上限沿用原值，
另保留 snapshot processCount 接受的 1000 项历史及 push 后 pop 的瞬时空间。
不改变 count+逐项 Vector3 编码、逆序求和顺序、Mirror 符号操作及 ECS 拷贝。
Mirror 遍历两个连续区间，避免链表指针追踪；不是此前的 deque 候选。

先用真实 engine 验证每组128步轨迹，再执行计时；增加 1000项恢复边界检查，
防止环形缓冲悄悄丢弃既有可接受状态。候选完整功能检查若失败，立即撤回。

保留条件：主负载 CPU 成本中位下降至少10%，配对 bootstrap95%区间支持正收益；
其余各组 CPU 中位回退不超过3%。最多8组，若结果不确定，本轮不扩大预算。
保留前必须完成质量门禁、长局/RSS与恢复检查。未保留候选不作为加速成果。
撤回时仅恢复本候选的三份原文件，核对恢复后的 source manifest 与 O1 相同，
重新构建隔离产物；不恢复其他文件，不覆盖既有用户修改。
