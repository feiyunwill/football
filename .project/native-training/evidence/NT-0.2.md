# NT-0.2：原生训练后端基线

日期：2026-10-14。结果：通过以下限定范围的实现与验收，提交后登记任务 commit。

实现：共享 C++ headless simple115v2/scoring 环境，默认/v2 离散动作映射、左右
视角、单/多人观测、结束条件、Gymnasium 接入、1..256 步预设动作批量处理，
及隔离的基准测量模块。新源文件已登记到 sources.cmake。

验收：

- `gfootball.test_native_training`：13 项测试，含 11 个受控球员、逐帧 Python
  对照、实际进球、结束、批量合法/非法输入、输出寿命、异常清理和所有权。
- 原有 `GymnasiumNativeTest` 的 checker、seed/global RNG、TimeLimit/match
  terminal、invalid/close 四项回归通过。合计本轮 17 项，10.030 秒。
- `engine_native_training_contract` 实际执行通过：joint/batch admission、
  terminal prefix、reset/replay hash 和重复 close。
- `git diff --check -- engine gfootball .project/native-training` 通过。

Python 运行环境：`/tmp/football-native-training-venv/bin/python`。
验证扩展：`/tmp/football-native-training-stage/gfootball_engine`，对应当前源码
的隔离构建 `/tmp/football-native-assessment-20261014`，非仓库旧 bin 产物。
NT-0.3 将补充永久构建/测试入口、日志和完整源码/产物指纹。

审查修正：错误线程的公开 `step/reset/close/render` 曾进入异常清理或修改
RNG/lifetime，导致 `env._closed=True` 但 owner 不能释放资源。新增回归测试
修复前稳定失败于 `assertFalse(env._closed)`；现先核对 native owner，再进入
公共状态改变与异常清理，修复后测试通过，owner 可继续 step 和正常 close。

范围限制：本任务不是完整产品验收；完整原有 Gym（包括图形）、打包/安装、
跨平台与长期训练仍需相应阶段验收。批量调用不穿过外部 Gym wrapper，文档
已说明其截断语义。暂无无条件性能保证。
