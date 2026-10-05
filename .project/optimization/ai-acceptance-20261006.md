# AI 正式回归证据（2026-10-06）

`tactical_integration`、`ai_decisions`、`training_reliability` 和 `ai_regression` 的正式质量检查均为 `verified`。`ai_regression` 以固定的 11v11 AI 对 AI 赛程覆盖种子 42–65，每个种子 6,000 帧；另对首尾种子复跑，并以 3,000 帧验证 Release 与 ASan/UBSan 的结果一致。正式报告为 **919 项断言、零跳过**，34 份命令日志的 SHA-256 均已回读核对，两种构建的测量二进制哈希与报告一致。

与封存基线对比，24 场的配对比赛积分、实际踢出的传球与射门、犯规和无效意图率的差值区间均为零；左侧 5 胜、右侧 4 胜、15 平。详见 [正式报告和逐次日志](evidence/ai_regression_formal_20261006/report.json)，报告 SHA-256 为 `5787ddc3571328df3811bf22d997b86e2b6d5b9486e0346525f9e5260f7663df`，基线 SHA-256 为 `baef37cdfbf9873f7dd92db076e6053cc6871aea60be2ed0162f5e20ce2fa152`。

这项检查证明当前代码相对封存基线没有退化，并覆盖确定性与 Sanitizer 一致性。它不替代实际交互体验评估；`ms-25.1` 仍依赖尚未通过的渲染里程碑，不能标记完成。
