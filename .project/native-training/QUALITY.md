# 原生训练持续验收

入口（Linux/WSL，先安装工程系统依赖和 Python validation 依赖）：

```sh
python .project/native-training/test_quality.py -v
python .project/native-training/quality.py run \
  --build-root /tmp/football-native-quality-build \
  --output /tmp/football-native-quality-evidence
python .project/native-training/quality.py verify \
  --output /tmp/football-native-quality-evidence
```

run 每次实际运行完整 validate.py，不以旧成功报告跳过测试。output 必须是新目录，
build-root 必须在仓库外；本地可增量构建，CI 在新 runner 的 RUNNER_TEMP 从干净
checkout 构建。构建 C++23、--parallel 1，Python staged binding 与 native
使用同一 core，并运行数值/场景对照、快照/恢复、资源、worker/采样、数学、真实
训练/跨进程续训/评估等测试及八个 C++ 合约。任何命令失败返回非零。

verify 核对当前完整源码/资源 manifest、验收脚本/门禁/自测/CI 配置的哈希、全部
22 个必需命令的成功记录和原始日志哈希；必需 Python suite 至少 72 项且不能
skipped。schema2 还核对目标 Python 的版本/路径、八项运行/构建依赖版本、
cmake/CC/CXX 可执行文件身份、平台及编译相关环境；源码、工具、依赖、runner
或 CI 规则变化要求重新验收。verify 的 --python 应指向原验收解释器，默认是
当前解释器；不是用缺少依赖的另一个 venv 为该环境宣称通过。单纯文档/ledger 更新不
改变模型源码身份。报告是可检查的本地证据，不是防伪签名或远程 CI 已运行的证明。

增量目录只复用于相同 compiler；同一工具的 c++/g++ 别名保留缓存路径，避免
CMake 自动清空缓存丢失外部输出配置。切换真正的 CC/CXX 请使用新外部 build-root。

`.github/workflows/native-training.yml` 在 master push/PR 和手动触发时执行
独立作业，不使用 continue-on-error，不修改旧 `.project/quality.py` 和
optimization manifest，不自动提升已有 milestone 状态。GitHub branch protection
是否要求此作业由远端仓库配置决定；本任务没有修改远端保护或发布代码。

自测通过故障注入覆盖：失败报告/命令、遗漏/重复检查、缺失或篡改日志、旧源码
或验收规则、环境/工具变化、跳过/过短 suite、越界日志路径。首次本地验收不等于 Ubuntu/Python
3.11 的远端 CI 已成功；平台实际验证范围在 NT-5.2/NT-5.3 单独记录。
