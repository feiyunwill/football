# NT-5.2 — 实际 wheel 安装与原生交付

2026-10-15。生产基线 HEAD `01afc6852fd5a7ea66bc5bbd7e336bac668ac5e5`。
新增 validate_delivery.py、installed_probe.py、package_native.py 与干净原生
合约验证器；使用说明 DELIVERY.md，平台/ABI 范围 PLATFORMS.md。

从 Git 提交导出 engine/gfootball/third_party/构建元数据（不包含庞大的无关
.project 诊断），在全新外部目录真实 PEP517 编译。检查生产工作树无 diff，
当前 1224 项源码/资源逐项对应；39 个文本路径仅 Git CRLF/LF 归一化，资源
要求原始字节一致，导出文件另有完整 manifest 与 archive SHA256。

实测 wheel：`gfootball-2.10.3-cp314-cp314-linux_x86_64.whl`，SHA256
`63e822e05c8c8e901577f1b9ef11178521e64b48869184e1e286dced77144c28`。
全新 venv 安装依赖和 wheel，pip check 通过；从仓库外 Python -I 验证
包/extension/data/font 路径全部位于该 venv，原生 Gym 多人/stack/rewards
及 snapshot restore 实测通过。完整 72 项安装后测试通过，93.527s，无 skip。

原生包从同一干净编译副本继续 bindings OFF 构建，含 ELF/core/data/fonts/
许可证、launcher 和文件哈希 manifest。完整搬移后 ldd/readelf 确认 $ORIGIN
解析实际 bundled core，无开发 build RPATH、缺失库或 Python adapter/interpreter
链接。四个独立进程实际执行 full2/prefix1/resume1/frozen0：完整 checkpoint
字节、后续 iteration 和冻结评估一致，评估不改变训练状态。

最终交付运行证据：`evidence/nt-5.2-delivery-20261015-d/report.json`。
它显式引用 B 轮干净 wheel 编译报告并核验 archive、wheel 和 build logs 哈希；
重新创建另一个全新 venv 安装和运行，不把重用已核验的编译证据冒称第二次干净
编译。额外 `evidence/nt-5.2-native-contracts-20261015-a/report.json` 从外部
编译目录运行八个实际 C++ 合约，资源取自搬移后的 package，core SHA 与 package
完全相同。当前生产 fingerprint 仍为
`77856efdadd172e065bc9289b65deaa0339eddb5aa8b22f003f7f0759bb54c6c`。

A 是尚未处理 Git 文本换行归一化的失败验收；B 的 wheel 构建/安装成功，但
packager 没覆盖 wheel 缓存中的 CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE，导致
复制路径错误。修复为显式设置所有 runtime/library 输出目录。C 的运行 core
实际正确，但 verifier 未归一化 ldd 的 bin/../ 路径，误判失败；改为 resolve
后比较。A/B/C 保留失败事实，只有 D 与最终八合约报告作为通过依据。

二进制/venv/archive 保留在 `/tmp/football-native-delivery-20261015-b`，不提交
生成产物。测试脚本、源码来源、产物/日志哈希及报告提交；没有 push 或发布。
Linux/WSL、glibc2.44/GCC16.1.1/CPython3.14.7 实测。3.11 CI 已配置未远端
运行；其他 Python、Windows/macOS 未扩展为已验证支持。包不是 manylinux、
abi3 或静态发行，仍依赖兼容系统动态库，checkpoint 仍需同构建/ABI。

图谱 Verify tier，project root-work_space-football，generation
2026-10-14T23:00:00Z。setup.CustomBuild.build_extension 用图定位后精确源码
核对；当前新增 material paths metadata_match，无记录缺口。MANIFEST.in 的
coverage not_tracked 通过直接 source fallback 核对，不以图 absence 作结论。
