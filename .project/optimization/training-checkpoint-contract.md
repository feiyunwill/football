# PPO 训练检查点可靠性

`BUILD_RL_TRAINING=ON` 的原生目标使用仓库固定版本的 RLtools。首次拉取仓库后运行
`git submodule update --init --recursive`，然后配置并构建
`cmake -S engine -B /tmp/football-rl-build -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=OFF -DBUILD_RL_TRAINING=ON`
和 `cmake --build /tmp/football-rl-build --target rl_football_training -j 2`。

检查点包含 RLtools PPO 核心状态。写入采用同目录临时文件、同步、原子替换和目录同步；
读取限制为 64 MiB，拒绝符号链接及非普通文件。TAR 尾部另有版本、长度及
SHA-256 校验；加载前把当前编译配置的张量元数据与文件逐项比对。
早期未封装的 TAR 不会直接加载。训练进程收到读取或写入错误会退出，
不会悄悄从新策略重新开始。

`--max-loop-steps 1 --save <prefix>` 运行一轮 512 环境步的有界检查；
`--load <prefix>_final.tar --max-loop-steps 1 --save <new-prefix>`
跨进程恢复并推进一步。`--save-interval` 必须大于零。当前 GameEnv 包装器
共享一个全局实例，因此编译期将 PPO 环境数固定为 1；11 名左队球员由共享
策略控制。

运行 `python3 .project/checks/training_reliability.py` 可重建目标并检验保存、
跨进程恢复、损坏和维度错误诊断，以及原子文件测试和 Debug 编译参数。
这项检查只证明训练流程和检查点可靠性，不证明策略胜率或比赛手感；
相关里程碑仍须各自验收。
