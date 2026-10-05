# 产品长时运行证据（2026-10-06）

独立执行 `python3 .project/checks/product_soak.py --cpu 0` 已通过：种子 42、43、44 各测量 36,000 个 11v11 逻辑帧，Release 与 ASan/UBSan 各合计 **108,000 帧**，报告为 **406 项断言、零跳过**。每个种子的输入、热身、最终状态、检查点和活跃帧轨迹在两种构建间一致；原生快照回放与日志校验通过。运行不覆盖图形呈现或广域网。

| 种子 | Release p99 | Release RSS 增长 | Sanitizer p99 | Sanitizer RSS 上界 |
| --- | ---: | ---: | ---: | --- |
| 42 | 6.180 ms | 132 KiB | 40.764 ms | 通过 |
| 43 | 7.783 ms | 132 KiB | 46.235 ms | 通过 |
| 44 | 6.748 ms | 132 KiB | 55.481 ms | 通过 |

Release 三组均通过 50 ms 逻辑帧 p99、4 MiB 增长上界及 256 KiB 平台期检查。Sanitizer 的 RSS 采用独立的 256 MiB 工具开销上界；Sanitizer p99 只记录，不作为产品版帧时预算。Sanitizer 未报告 ASan/UBSan 错误。

[归档](evidence/product_soak_5754078e079c.zip)包含原始报告和 12 份命令/测量日志；归档 SHA-256 为 `f1f0cf59befb3f75ff1da1ddc165d49b87390e615406b2cdbba5f1c19349e0a6`，报告 SHA-256 为 `5754078e079cec6ae299d8198ea6abd1f3db3587cad81673098194b974ebc786`。归档前已重新校验当前源码清单、全部日志和两种构建的测量二进制；归档回读及重复生成得到相同哈希。可用下列命令独立校验归档：

```sh
python3 .project/scripts/archive_product_soak.py --verify \
  .project/optimization/evidence/product_soak_5754078e079c.zip
```

这份结果是独立长时运行证据。质量编排中的 `product_soak` 已完成正式复验，状态为 `verified`；发布里程碑仍受上游渲染门禁和其他待刷新证据约束。

## 正式质量编排复验

`product_soak` 的正式运行再次完成 Release 与 ASan/UBSan 各 108,000 个测量帧，**406 项断言、零跳过**，三个种子的完整轨迹逐一匹配。Release 三组 p99 分别为 **8.320、9.156、6.192 ms**，RSS 增长均为 **132 KiB**；Sanitizer 三组 p99 分别为 **57.535、34.605、28.764 ms**，独立工具开销上界均通过。已用原生验证器重算六份原始日志，复核 12 份命令日志、827 项源码与资源清单、Release 与 Sanitizer 测量二进制哈希。

[正式归档](evidence/product_soak_cc2641c37587.zip)的 SHA-256 为 `c4a8531563e126671147209bffd8df442780066718ccdf464045d08c281cabd6`，正式报告 SHA-256 为 `cc2641c37587b2c6ecdb8fbd46345d46630efd6523117c074b1494ca67331492`。归档经独立回读校验，并重复构建为完全相同的字节。校验命令：

```sh
python3 .project/scripts/archive_product_soak.py --verify \
  .project/optimization/evidence/product_soak_cc2641c37587.zip
```

这证明当前逻辑帧长时稳定性，不覆盖真实图形呈现或广域网；发布验收仍以全部里程碑和正式门禁为准。
