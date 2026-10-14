# NT-2.2 — C++ 完整训练状态与事务性恢复

完成日期：2026-10-14。最终验收通过。

实现：NativeTrainingEnv::get_state/set_state；版本 1 的 FTRN 包含 FSTA 内核、
每 agent checkpoint、score/mode/possession 历史、规范帧历史及 ready 状态。
导出/恢复要求已成功 reset；closed 或 mutation 失败的环境拒绝。

## 恢复边界

先解码并核对场景、训练选项、控制人数、cadence 和构建/资源/尺寸身份；
训练侧对象全部提前分配。内核恢复后重建 SharedInfo，检查 readiness、比分、
模式/持球历史及 stack 最新帧，不执行物理 tick 或重新结算奖励。
训练状态以 noexcept move assignment/swap 一次提交。
任何内核或后置检查失败均恢复旧内核/config；训练对象保持原值。回滚失败关闭
环境并报明确错误。get_info 用 RAII 保持 observation tracker 的异常平衡。

身份由源码/构建配置的有序 SHA256 清单生成；源文件内容变化触发 CMake
重新配置，不依赖 Git HEAD。快照操作核对实际 data 文件清单/内容符合构建时
manifest，加入 runtime dimensions 与 sizeof ABI 信息。真实资源变更会拒绝。
格式及场景字段顺序见 [SNAPSHOT.md](../SNAPSHOT.md)。

## 验收覆盖

- 左右队×两种布局×checkpoint 开关×stack 开关的 16 组合：保存两步后的
  live 状态，在独立 C++ 环境恢复后逐步比较观测、奖励、结束与 kernel digest。
- terminal 保存/恢复，拒绝继续 step；terminal 目标恢复 live 状态后批量执行，
  逐行对照原 scalar 序列及首终态前缀。
- 1/11 人及 builtin AI action、cadence=3；非零部分 checkpoint 保存后继续；
  稀疏近门场景真实进球及 checkpoint 填满。
- 错误版本/容量由格式合约覆盖；恢复合约覆盖截断、超限、身份/seed/尺寸/
  选项/cadence 不匹配；内核部分读取、unexpected external state、错误 ready、
  比分历史、stack 最新帧触发真实 rollback。
- 拒绝后比较 kernel digest、完整训练字段，并继续与独立 control 环境逐步对照。
- 私有 symlink 数据集测试原资源重定位仍兼容，缺失/新增文件及内容变更拒绝；
  不修改仓库资源。
- 永久 validate.py 同时运行原生、格式、恢复合约及全部原有 Python/Gym 测试，
  bindings OFF 依赖检查和 Python/native core artifact 哈希相等检查。

最终证据在 `evidence/nt-2.2-integration-20261014-b/report.json`；首轮 a 保留
用于追溯。31 项 Python/Gym 测试通过（27.605 秒），三个 C++ 合约通过；
Python/native 使用相同 core artifact。1194 个源文件/资源的前后 fingerprint
一致：`bfa41e1be70c4a2787d25c5c5824e9a7482db5eb69eb20ef7a4e0dfd43cea002`。
图 coverage generation 2026-10-14T05:20:15Z，任务材料路径无记录缺口；
调用边界及 RAII 以具体源代码核对，coverage 不证明完整性。
此任务不声称完成 Python/文件快照、新进程长期回放、恢复失败导致
回滚本身失败的运行故障注入或全内核 sanitizer；这些由 NT-2.3/NT-2.4 和
阶段 review 继续核对。格式层已有独立 ASan/UBSan 证据。
