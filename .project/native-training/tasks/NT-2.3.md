# NT-2.3 — Python 接入与原子文件

完成日期：2026-10-14。最终集成验收通过：43 项 Python 测试（35.270 秒）、
三个 C++ 合约、bindings OFF 依赖检查；Python/native core artifact 哈希一致。
1196 个源文件/资源的前后 fingerprint 一致：
`20f54497d215f1a9d552e7be053d159a8546a868afbcc08f43d817ad7b9ea09a`。

范围：原生 bytes 绑定、raw Gym 环境快照、标准 wrapper 状态、原子文件读写。
格式、平台及状态范围见 [SNAPSHOT.md](../SNAPSHOT.md) 和使用文档。

绑定在复制前检查输入上限；释放 GIL 时只使用 C++ 的 owned string，重获 GIL
后才返回 Python bytes。Python owner 检查先于文件操作、配置、RNG 或内核变化。
Gym 元数据及 PCG64 state 严格验证并提前准备；native 恢复失败不提交 Python 值。
wrapper 元数据在 native 变化前校验；wrapper 提交失败回滚 raw 状态与所有 wrapper，
回滚本身失败关闭整个环境并报错。

## 测试覆盖

- 格式损坏、逐处截断、尾随字节、元数据/输入长度/深度/路径预算及非 regular 文件。
- 文件 fsync/replace 故障保留旧文件；清理失败保留主异常。
- 实际子进程停在替换前，然后被杀死，旧文件依然完整可加载。
- 原生/Gym bytes 与文件 round-trip，后续动作及未来 reset 的 RNG/episode 一致。
- 新 Python 进程从仓库外工作目录加载文件，逐值对照观测、奖励、结束和下一次 reset。
- 未知 wrapper、TimeLimit 参数、元数据、PCG64 错误、mutable bytes/超限输入拒绝。
- TimeLimit 截断时点、正常 terminal、terminal 恢复拒绝 step、live 恢复可继续。
- PassiveEnvChecker 首步保留的历史数组重建；OrderEnforcing 和 checker flags。
- wrapper 提交后故障注入：内核、RNG/config 与 wrapper 回滚，目标可以继续操作。
- 错误线程在文件访问前拒绝，原状态及创建线程的后续 step 保持可用。

首轮 a 证据对应 raw API；最终完整证据为
`evidence/nt-2.3-integration-20261014-b/report.json`。永久 validate.py 包含新测试，
同时回归原有 native/Gym suites、三个 C++ 合约、bindings OFF linkage 和相同 core
产物检查。NT-2.4 继续长期多 seed/scenario、资源与全内核 sanitizer 验证；
本任务的短回放不作为这些门禁的替代，也不提升其他产品里程碑状态。

图 coverage generation 2026-10-14T05:34:18Z，材料路径无记录缺口；第三方
Gymnasium wrapper 源码通过安装环境 inspect 读取，不能用本仓库图证明其行为。
Unix fork 的既有 owner 合约仍由原训练 suite 回归；snapshot 新进程测试使用
独立启动的 Python，不依赖 fork 继承已初始化引擎。
