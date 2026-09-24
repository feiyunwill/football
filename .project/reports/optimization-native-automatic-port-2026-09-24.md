# 原生服务自动端口：正式接入与验收

归属 ms-23.1 → plan-23.1.1 → task-23.1.1.2。端口 0 功能及永久会话门禁已正式接入，专项门禁通过；关联完整门禁仍在串行重验，Host/Join 菜单及整个网络里程碑尚未完成。

## 实现

CLI 原先拒绝端口 0，而实际监听器已支持原子分配端口。integrated_server.cpp 现允许端口 0，由监听器完成绑定后输出实际端口。public UDP、TCP 和 UDP 三个入口共用同一实现。

新增 native_automatic_port_probe.py 使用两个同时存活的服务、两个真实原生客户端验证端口和会话。native_automatic_port_contract.py 在 Release 与完整 Debug ASan/UBSan 下构建正式目标，检查所有编译单元的语言/调试/检测选项，固定源码及二进制哈希并执行三个入口。保留 30 秒启动和 45 秒客户端期限、泄漏检查及无 O1 的 Debug 配置。

optimization/program.json 新增 native_session_ports，并附加至原网络任务、计划、里程碑的检查列表。network_reconnect、network_regression 等既有要求全部保留，未因专项通过而提高整个网络里程碑状态。

## 正式证据

native-automatic-port-adoption-20260924-b 完整采纳四个文件，源码清单 1137 项；sources-after.json 和 adopted-files.json 固定本次版本。正式 native_session_ports 门禁耗时 166.397 秒，通过 1924 个断言、6 组双服务、12 个真实客户端。各客户端确认 100 帧并校验至少 10 个 hash，种子对应正确，回放文件存在；各服务的端口非零、同时存活时不重复且由对应进程持有，退出均正常，无 Sanitizer 错误。

10 条执行命令日志哈希及源码清单已独立核对，见 port-verification.json。正式日志 native_session_ports-1790218548966388991.log，SHA-256 25a1474a92eaa71b11b66e487f717ffcc9751dcc406eebaee06b83a8cfb1066e。

正式 quality_selftest、native_boundary 和新版 tactical_integration 已通过；战术为 32 项结果、162740 个断言及 24 次独立回放，正式日志 SHA-256 f9340a1f582b03b0deb37c03d8df4a48802addbfcd2f692d514799785186a104。当前继续 input_contract → framework_regression → ai_decisions。整体采纳阶段尚未结束。

## 保留的失败与范围

私有候选 A 的 6 组/12 客户端先行验证已通过。正式采纳 A 在备份尚不存在的新检查器文件时失败，只写入 integrated_server.cpp。旧阶段输入及失败记录未修改；新阶段 B 先读取全部候选、区分新增和已有文件，再完成采纳。原失败不是运行时端口测试失败。

完整端口验收仍是本机实际网络会话范围，没有代替 WAN、设备延迟、完整恢复、菜单、暂停与存档验收。下一步暂停集成必须进入实际帧线程及客户端路径，详见 optimization-native-pause-integration-2026-09-24.md。

## 2026-09-24 提交时验证快照

自动端口 adoption B 已结束（exit 1）：7 项正式检查中 6 项通过，input_contract 失败。已通过 quality_selftest、native_session_ports、native_boundary、tactical_integration、framework_regression、ai_decisions；7 份正式日志的 SHA-256 已核对。输入失败来自 actual-input-windows 内的 windows 子命令，尚未确定根因；此前版本通过的输入验收不能代替当前版本结果。失败日志：.project/optimization/evidence/input_contract-1790218989295654624.log。

自动端口专项仍为通过：Release/full Debug Sanitizer 下 6 对服务端、12 个真实客户端、1924 项断言。整体产品质量尚未验收通过。

allocator-regions B 已从排队进入 instrumented-0 阶段；提交时仍在运行，结果待后续记录。该诊断不改正式源码；原始架构 RSS 失败仍未关闭。用户已授权本次提交及推送；以下旧条目保留为历史记录，其运行状态以本快照为准。
