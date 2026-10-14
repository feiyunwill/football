# NT-1.2 两套 115 维布局

2026-10-14。已实现并通过独立子任务验收，S1 阶段整体 review 尚未进行。

- C++ constructor 可选 fixed_positions，默认保留 v2；Python representation
  显式选择 compact simple115 或固定块 simple115v2。
- 四个 compact team 块根据实际队伍人数排列，88 值前缀统一补 -1；尾部 27 值
  共用编码。每 agent active 各自独立，左右视角保持原约定。
- full、sparse、asymmetric、left/right、single/joint 的 reset/scalar/batch
  均实际与 Python 对照；full 两种布局相同、sparse 两种布局不同。
- 纯 C++ 合约检查两套布局的 padding、共同 tail、逐步奖励及引擎 hash。

永久验收入口本轮运行命令：

```bash
/tmp/football-native-training-venv/bin/python .project/native-training/validate.py \
  --python /tmp/football-native-training-venv/bin/python \
  --build-root /tmp/football-native-assessment-20261014 \
  --output .project/native-training/evidence/nt-1.2-integration-20261014
```

结果：**26 项 Python 测试通过**（17 原生 + 9 原有 Gym），24.947 秒。bindings
OFF 的纯 C++ 合约通过，无 Python/adapter 依赖，Python/native core artifact
相同。1186 个 source/resource 文件前后指纹相同：
`8004f0710b24125671bce37501f7131bdf6dc8469b7751895556c80af4a5cab7`。

原始命令、日志、环境版本和产物哈希见
[完整证据](nt-1.2-integration-20261014/report.json)。
新参数保留源码调用默认值；新扩展和纯 C++ 合约均重建。尚未发布 ABI 兼容性
承诺或 wheel；跨平台/安装验收保持 S5 范围。
