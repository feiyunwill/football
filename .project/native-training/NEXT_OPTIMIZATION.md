# 下一阶段实验入口

计划与进度：[计划](../optimization/next-optimization-plan-20261015.md)、
[状态](../optimization/next-optimization-state.json)。在 Linux/WSL 仓库根目录运行，
使用已有的训练 venv、系统依赖与隔离 Release 构建。下列目录名仅是示例，
每次使用新的 output/work-root；全部构建、测试和测量串行执行。

## 当前基线

```sh
PY=/tmp/football-native-training-venv/bin/python
BUILD=/tmp/football-native-assessment-20261015
$PY .project/native-training/quality.py run --build-root "$BUILD" --output /tmp/new-quality-evidence
$PY .project/native-training/benchmark_next_baseline.py \
  --build-root "$BUILD" --quality-output /tmp/new-quality-evidence --output /tmp/new-baseline-evidence
$PY .project/native-training/measure_step_latency.py \
  --build-root "$BUILD" --output /tmp/new-latency-evidence
```

基线绑定代码/资源、目标环境和实际加载的 .so。预设动作与反馈闭环分开，
八组负载各运行八次；分阶段 profile 的计时开/关状态哈希必须一致。
原生 CLI 的 PPO 计时包含启动和快照；逐步尾延迟另作诊断，不与无插桩吞吐混用。
worker 资源报告中的既有 heuristic 结果不能当作 PPO 训练吞吐。

## 学习效果

```sh
$PY .project/native-training/test_learning_study.py -v
$PY .project/native-training/validate_learning.py --build-root "$BUILD" \
  --work-root /tmp/new-learning-models --output /tmp/new-learning-evidence
```

执行前保存 protocol.json：三个配置各99,840 joint transitions；仅用 pilot seed7
和调参集选择配置。随后在五个独立训练种子上各训练同样预算，以四批50局组成
200场保留场景，比较 initial/sample/argmax/random/builtin AI。
五个训练种子共享这200场评估场景，不把1000局当作1000个独立训练重复。

`passed` 仅表示实验协议正常执行。是否达到学习目标，必须同时查看
`learning_passed`、每种子成功率和两个配对区间。成功按真实进球判断；
checkpoint shaping reward 不能替代进球。模型文件在外部 work-root，报告保存 SHA256。
本实验只涉及项目拥有的 native empty_goal，不证明11v11水平或任意Python场景兼容。
empty_goal 的起始位置固定；保留评估种子不构成对新位置或新对手的泛化证据。

## 优化候选

```sh
$PY .project/native-training/validate_candidate.py --python "$PY" \
  --baseline /tmp/preserved-baseline --candidate "$BUILD/validation-stage" \
  --output /tmp/new-candidate-evidence --steps 1024 --repeats 8 --primary-only
$PY .project/native-training/decide_candidate.py --report /tmp/new-candidate-evidence/report.json \
  --output /tmp/new-candidate-evidence/decision.json
```

必须先按候选协议保留原始二进制、manifest与原文件。主负载筛选通过后仍需运行
完整八组矩阵及长局/恢复/RSS检查；`primary_only` 不能授权保留候选。
本轮球历史环形缓冲已因未达到门槛撤回，补丁仅存实验归档，不默认重新应用。

## 真正的多进程 PPO

```sh
$PY .project/native-training/benchmark_ppo_workers.py --build-root "$BUILD" \
  --work-root /tmp/new-ppo-worker-build --output /tmp/new-ppo-worker-evidence
```

工具在仓库外构建一个小型 pybind 诊断模块，直接复用生产
categorical_policy.cpp 与 ppo_math.cpp。父进程以冻结策略决定动作，现有 spawn
workers 推进真实引擎，每次收齐四个终止/截断episode后按episode/step排序并更新。
每个更新至多128个joint transitions；1/2/4 worker、1/11人、cadence2/10均做三轮。
报告包括实际推理、callback、PPO update、总吞吐和进程资源，逐轮比较模型与轨迹。

采样 RNG 以 episode/step 为键，与 native CLI 的顺序 RNG 协议不同。诊断 JSON
checkpoint 只在完整episode/update边界保存，下一轮总会reset所有被分配的环境，
因此不存在需要恢复的活跃episode；它不是 FPPO 模型格式，也不是公开安装 API。
必须通过新进程、从1 worker切到4 worker的字节一致续训验证，才报告恢复成功。
`twofold_target_observed` 与协议通过分开；小样本WSL吞吐不构成跨机器加速承诺。

## 平台交付

既有 `validate_delivery.py` 支持在源码指纹相同且原始构建日志、wheel哈希可验证时，
复用已审计的干净wheel构建，重新创建独立安装环境并验证迁移包、训练与恢复。
GitHub工作流已配置Python3.11/3.14；本机只有3.14，远端未实际执行的版本保持待验证。
GPU及完整产品发布仍沿用原有依赖与验收规则。

## 本轮证据核对与模型交付

```sh
$PY .project/native-training/audit_next_iteration.py --output /tmp/new-iteration-audit
```

该命令专门核对2026-10-15这轮已保存的目录与外部模型文件，不重新跑长训练。
它会核对当前源码、工具、原始日志、模型、统计区间和候选决定，并执行两组门禁自测。
`passed` 表示本地证据相符；远端CI、GPU及全部2×目标仍独立记录。
模型和匹配的Linux运行时可从
[归档](evidence/o2-learning-20261015-a/trained-models-linux.tar.gz)获得，包含LICENSE和使用说明；
它仍需要同版本仓库资源及兼容系统库，不是跨ABI发行包。
