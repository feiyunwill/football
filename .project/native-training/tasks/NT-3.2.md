# NT-3.2 — 引擎热点候选对照：不保留容器优化

2026-10-15。NT-3.1 定位 engine step 占 native 单步墙钟约 93%–98%。
本任务选择一个内部热点候选并完成真实 baseline/candidate 对照。结论：
正确性一致，但收益不稳定，撤回生产代码的 deque 改动，不扩大优化范围。

## 热点证据与候选

GNU gprofng 2.47 对真实 native rollout 采样；collector signal 排除初始化、
warmup、reset 和 snapshot/resource hashing。5ms 的首轮仅有 0.845 秒样本
权重，明显小于 18.635 秒 user CPU，仅作 provisional scout。第二轮 16384
steps、100ms 采样，样本权重 62.6 秒、实验时长 63.24 秒，覆盖更合理。
Node::RecursiveUpdateSpatialData exclusive 10.70% / inclusive 19.01%，
Ball::Mirror exclusive 7.35%。文本日志与 SHA256 在两份 cpu-probe evidence。

候选将 Ball 和 BallComponent 的 401 项 history 从 list 改为 deque。
push_back/pop_front、clear/resize、正向序列化、反向求和顺序不变，未跳过
Mirror、空间更新或物理计算。Ball::ProcessState 编码 count+逐项 Vector3，
不写容器对象。原 NT-3.1 .so 按字节保存为 baseline，记录源码及产物哈希。

图 coverage generation 2026-10-14T20:30:08Z：三个候选文件无记录缺口；
match.cpp 有 partial 1397 行，已读取该范围（MatchStepFn 成员函数类型）。
Match::Mirror 的精确源码确认 this->ball->Mirror()；图的 Ball inbound
关系不完整，不能代替源码调用核对。coverage 不构成穷尽证明。

## 对照结果

候选集成通过 47 项 Python 测试及四个 C++ 合约。A 轮 512 steps×8 次
交错运行，墙钟波动较大。B 轮固定最小可用 CPU，1024 steps×8 次交错，
同时测量 process CPU 和墙钟。1/11 人×cadence 2/10×预设/反馈共八组；
每组先对照 128 步的观测、奖励、终止、比分及逐步 kernel digest，计时轮
校验最终 digest。所有对照均通过；B 源码前后指纹一致：
`e54a8c97a63146d5e260e581224d0acf76c96e7652336597c6d0bc7df41a7c86`。

比值为 baseline/candidate，大于 1 表示候选更快：

| 玩家 | cadence | 动作 | 墙钟中位比值 | CPU 中位比值 | CPU 胜出次数 |
|---|---|---|---|---|---|
| 1 | 2 | 预设 | 1.0417 | 1.0384 | 6/8 |
| 1 | 2 | 反馈 | 0.9966 | 0.9964 | 4/8 |
| 1 | 10 | 预设 | 1.3453 | 1.3360 | 6/8 |
| 1 | 10 | 反馈 | 1.0988 | 1.0988 | 5/8 |
| 11 | 2 | 预设 | 0.9889 | 0.9886 | 4/8 |
| 11 | 2 | 反馈 | 0.9242 | 0.9228 | 3/8 |
| 11 | 10 | 预设 | 1.3062 | 1.2858 | 5/8 |
| 11 | 10 | 反馈 | 0.9664 | 0.9687 | 4/8 |

四组 CPU 中位数退步，多组配对比值跨度很大，WSL 主机环境仍存在波动。
本实验不足以支持稳定收益，不宣称通用加速或精确因果分解。反馈策略是
读取最新观测的轻量确定性 heuristic，并非 PPO 推理。

## 归档与收尾

- `evidence/nt-3.2-cpu-probe-20261015-{a,b}`：采样文本及哈希。
- `evidence/nt-3.2-candidate-integration-20261015-a`：候选完整集成。
- `evidence/nt-3.2-comparison-20261015-{a,b}`：全部子进程日志、样本和报告。
- B 的 `tooling/` 保存当前测量脚本、baseline manifest、候选补丁及 SHA256。
  候选补丁通过 `git apply --check`，只归档而不应用到生产源码。A 使用
  固定 CPU/CPU-time 增补前的脚本，原脚本未单独归档；A 只作辅助证据。
- 已撤回仅三个候选源码文件，保留其他既有修改。容器改动未保留，因此
  不额外为该候选重建 sanitizer；S2 sanitizer 证据不冒称本候选验证。
- 原实现重新构建及完整集成记录在
  `evidence/nt-3.2-restored-integration-20261015-a/report.json`。
  passed=true：47 项 Python 测试、四个 C++ 合约及无 Python 依赖检查通过。
  源码前后指纹均恢复为 NT-3.1 基线
  `60835581fbebff949f465f011adb7953c90f0997f8af5d0728b15ecaa9b3c603`。

下一任务 NT-3.3：有界进程采样及确定性任务/种子协议。进入下一阶段仍需
NT-3.3、NT-3.4 和 S3 全局 review 完成。
