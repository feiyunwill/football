# 产品发布审计（2026-10-07）

在源码提交 `142d56c` 上，以 Linux x86_64、显式 Wayland 和本机 Mesa D3D12 驱动直接执行 `.project/checks/product_release.py`。审计执行了 193 项断言、零跳过，结果为 **失败**；[原始报告](evidence/product_release_direct_audit_20261007.json)的 SHA-256 为 `3ad435a83c08bab6e9af40943b09c47f259ee1f4149a61a6aaaa5ac6358c4819`。

框架、架构、性能、手感、网络五个里程碑（`ms-19.1` 至 `ms-23.1`）处于 `verified`。渲染里程碑 `ms-24.1` 仍因 1080p 帧时超过 16.67 ms 而 `failed`；AI 里程碑和三个产品交付任务随依赖链保持 `failed`。已通过的 AI、交互旅程与打包**直接检查**不能替代正式质量编排证据；审计相应检查项仍显示 `stale`。长时稳定性检查在本次审计时尚未结束，正式 `product_soak` 证据同样为 `stale`。阻断问题 `render-1080p-p95-20261006` 仍为 `open`。

这个报告是发布拒绝的可复核快照，不代表产品验收通过。后续需完成长时检查并按 `.project/scripts/archive_product_soak.py` 保存可验证原始归档，再解决渲染帧时并重新运行依赖链；只有正式发布审计通过后才能关闭交付任务。

## 后续：长时直接检查完成

同一份引擎源码的 `product_soak.py` 直接检查现已通过：种子 42、43、44 在 Release 与 ASan/UBSan 下各测量 36,000 帧，即每种构建 **108,000 帧**；**406 项断言、零跳过**。三个 Release 运行的逻辑帧 p99 分别为 **8.584、6.357、6.430 ms**，均低于 50 ms 预算。每个种子的 Release 与消毒器完整轨迹一致；三个 Release 内存增长、季度平台期、末段平台期和三个消毒器独立内存上界均通过。

[可验证原始归档](evidence/product_soak_47df5b84f4e6.zip)保存最终报告、12 份命令／运行日志、源码提交及二进制 SHA-256；使用 `archive_product_soak.py --verify` 独立复核通过。报告 SHA-256 为 `47df5b84f4e6e258a479f7b6ce5698b27bf3b9ee1789681842138c532fd66386`，归档 SHA-256 为 `aacbe3bc2688581f8fb7248056424ebf0fa5978fe1dbe3c7880cf52bd0e78e26`，被测源码提交为 `64000a5`。

这是直接检查结果。正式 `product_soak` 质量编排证据及其依赖链仍须按程序运行；渲染阻断问题未关闭，发布审计仍不得标为通过。
