# 永久验证构建隔离与证据保留

归属 ms-23.1 → plan-23.1.1 → task-23.1.1.2。问题来自验收驱动复用构建目录；正式源码与运行中的候选未修改。

状态门禁完成后，控制门禁再次配置同一组 Release/sanitized 构建目录，增加 FOOTBALL_TEST_X11_ROOT。两份 compile_commands.json 各增加 2 处私有 X11 include 参数，导致状态门禁的固定哈希不再匹配。其余 31 份状态输入与 28 份命令日志均匹配；81,100 项断言的已完成结果保留，但不能宣称整段串行验证的固定输入全程不变。

从当前编译记录中去掉新增 include 后，在独立证据目录恢复原始字节，哈希精确匹配：

- Release：70fadae665d7a1667adad3e868e632408ab829391641cf955599e6ed26e265d3。
- 完整 Debug：e84234e5e75b98a2d4bf991a41c4169da89320f4cc042e7845834d8f0bf52b02。

证据位于 native-state-permanent-progress-20260925-b/state-gate-checkpoint.json、compile-record-recovery.json 及两份 *-state-compile_commands.recovered.json。原执行目录未覆盖，差异记录继续保留。

native-validation-isolation-preparation-20260925-a/driver.py 已准备独立 state-build/{release,sanitized} 与 control-build/{release,sanitized}，每个门禁前后累计核验此前门禁固定输入。该驱动尚未排队或执行，必须在新阶段按原门槛实跑验证。

2026-09-25 控制门禁增量：永久验证 B 的 Release 共 19 项结果通过，涵盖 6 个普通客户端、3 个恢复客户端及 11 次独立回放。TCP/UDP 窗口分别确认 4732/4839 帧、完成 1002/1003 次呈现，退出 61.464/86.720ms；两个窗口独立回放合计 9571 帧通过。当前完整 Debug 控制验证仍在运行。检查点核验 2545 份控制输入与 44 份完成命令日志，无差异。旧日志只读统计显示呈现间隔中位约 97ms，窗口门槛通过不能代表产品流畅度达标。

对应证据：native-state-permanent-progress-20260925-b/release-control-checkpoint.json 与 release-render-gaps.json。已目视检查 TCP frame-40.png，能看到球场、球员与 HUD；这只证明该采样画面有内容，不替代完整图像回归。

模型变形优化的差分工具已准备在 native-skinning-lookup-preparation-20260925-a：同一真实 GameEnv 测试程序分别链接旧版与候选核心，覆盖 22 名球员、3 名裁判、两种种子/处理顺序、10 个姿态及两种 updateSrc 模式，预期 1000 个案例。记录完整源网格、输出顶点属性、索引和骨骼权重，并逐字节比较。工具尚未编译执行，不宣称候选等价或有性能收益。

当前唯一执行阶段仍为永久验证 B。后续先处理其完整 Debug 终态，再决定细分管线观测和模型变形候选验证；所有构建、测试、测量保持串行。
