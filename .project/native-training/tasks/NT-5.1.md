# NT-5.1 — 原生训练持续验收

2026-10-15。新增独立 `.project/native-training/quality.py` run/verify 和
`.github/workflows/native-training.yml`。旧 quality.py、optimization manifest
和既有 CI 作业没有任务 diff，不自动改变 milestone 验收状态。

run 实际执行完整 validator，必需 Python 测试禁止 skip；verify 拒绝失败、
缺少/重复命令、日志篡改/缺失、过期源码、旧 runner/门禁/自测/CI 配置。
报告记录 acceptance schema 与 infrastructure 哈希，运行期间规则变化失败。
CI 在干净 checkout 与新仓库外 build 目录使用 C++23、--parallel 1。
使用说明在 `QUALITY.md`。

六项故障注入自测通过：包含真实 CLI 非零退出和验证器失败传播；旧 quality
结构验收仍为 56 nodes、32 checks。没有 push，未宣称远端 CI 已执行；
Ubuntu/Python3.11 作业的实际远端结果需要提交后的授权运行，平台支持范围
在 NT-5.2 安装实验记录。

最终本地验收：`evidence/nt-5.1-integration-20261015-b/report.json`，由稳定
quality.py run 执行，并由 verify 再核验。包含 72 Python 测试、八个 C++
合约、实际训练/恢复/评估、native no-Python linkage 与共同 core 身份。
本地复用隔离增量 build，CI 指向新目录；干净外部安装/构建属于 NT-5.2。

A 轮完整测试本身成功，但期间修改 acceptance runner，外层 quality 返回
非零 `Acceptance runner changed`。A 保留作过期拦截记录，不作任务通过证据；
B 才是最终稳定实现的通过报告。源码/资源 fingerprint 仍为
`77856efdadd172e065bc9289b65deaa0339eddb5aa8b22f003f7f0759bb54c6c`。

图谱 Verify tier：project root-work_space-football，material paths coverage
generation 2026-10-14T22:42:58Z，metadata_match，无记录缺口。图谱定位原
quality main/check_state 后直接读取源码核对；无记录缺口不是穷尽证明。
历史 vendor source archives 的 partial parse 与当前门禁实现无关，未用其
absence 或图统计支撑本任务结论。
