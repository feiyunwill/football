# 训练观测布局修复与验证 — 2026-09-24

当前状态：观测越界修复已接入，局部编译期和 Linux 运行检查通过；完整训练可靠性和产品级验收未通过。

## 缺陷与实现

GameEnvWrapper 原先声明 128 列，但 observe 实际输出 147 个值：球状态 9、双方球员各 66、比分 2、比赛标量 4。对原始序列化函数体的有界写入对照确认有 19 次写入超出声明容量。

新增 observation_layout.hpp 统一特征数量、序列化顺序与补零逻辑，默认观测维度改为 147，保留全部特征。静态检查拒绝不足 147 列的配置和状态字段数量变化；包装器还要求输出矩阵为单行，列数与环境声明一致。独立的 constexpr 写入函数不依赖引擎、RLtools 或平台运行库，不分配堆内存。

新增永久编译期合约 rl_observation_static_contract.cpp 和运行合约 engine_rl_observation_contract.cpp，纳入 engine/tests 构建及 CTest。框架回归要求至少 703 项 C++ 测试，并明确要求 rl_observation_contract 出现；703 是验收门槛，尚不是完整框架运行结果。

## 已取得的证据

- MSVC 编译期检查：147 列与 160 列补零、非零/零状态、字段顺序、每列恰好写入一次、首尾哨兵；不足列数和字段总数变化均被拒绝。原函数体的对照确认 147 次写入、19 次越界。
- 对真实包装器声明及 observe 函数体做隔离实例化：合法矩阵通过，128 列及两行矩阵被拒绝。Matrix/set 使用明确的有界测试替身，因此这不是完整 RLtools 编译。
- Linux GCC 16.2.1：实际已接入的运行合约在 Release 与完整 Debug ASan/UBSan 下各通过 4 个场景、1850 条断言，未跳过；开启泄漏检查、错误即停止，未使用 O1。
- 8 项验收器单元测试通过，新增检查防止完整框架遗漏观测运行合约。
- 8 个修改文件哈希及 4 个候选文件逐字节一致性已核对。

不可变证据目录：rl-observation-layout-20260924-d、rl-observation-wrapper-20260924-a、rl-observation-adoption-20260924-a、rl-observation-adoption-proof-20260924-a、rl-observation-linux-20260924-a。

早先 A 的命令引用失败、B 的 Windows SDK 缺失、C 的命令文件换行失败均保留，未记为通过。MSVC 仅用于隔离编译期验证。RLtools Matrix::Specification 的 ROWS/COLS API 已对照项目 gitlink 所指 b32d9985c65a5e098a6bbf190fd994962d288b99 的官方源码，原文件和哈希已存档；没有安装或替换依赖。

## 正式验收与剩余范围

WSL 新命令执行已恢复，旧探针进程已消失；未由本轮重启 WSL 或修改全局设置。当前完整 Linux 源码清单为 1117 项，包含全部 12 个嵌套 UDP 夹具。native-canonical-adoption-gates-20260924-a 已开始依次执行原生边界门禁、正式 Debug ASan/UBSan 产品构建、143 项 UDP/观测合约及原完整框架门禁。终态应以该阶段 exit.json 和实际报告为准。

third_party/rl-tools 仍为空，完整训练构建尚未验证。旧 128 维检查点与 147 维模型的兼容性未验证，后续必须提供明确的维度/版本诊断；现有检查点原子写入、损坏处理、恢复失败时的行为、无主球有符号值及引擎实例生命周期等仍待修复和验收。本次观测修复不证明这些要求已完成。
