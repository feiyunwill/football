# 原生主机控制：暂停边界与确认记录候选

对应 ms-23.1 → plan-23.1.1 → task-23.1.1.2，承接[菜单功能对齐审查](optimization-native-menu-parity-2026-09-24.md)。本候选是主机暂停功能的协议组成部分，尚未接入正式源码，也未完成运行验证。

私有阶段 native-match-control-contract-20260924-a 已排在正式接入 B 的完整门禁及公共 UDP 对局成功之后，执行顺序串行。候选保存 epoch、Running/Paused/Resuming、权威下一帧和状态哈希，接受重复记录、暂停、新 epoch 的恢复准备及同 epoch 的恢复提交，拒绝跳跃、回退、边界改变和 epoch 回绕。确认记录必须匹配 epoch、帧和哈希，不能确认 Running。

编码保留现有 match_control.py 的明确小端字节语义。读取该头文件不等于协商了 native 或 Python match-v6 传输能力。计划验证：
- 28 项 GTest：独立固定字节样本、所有截断/多余字节、消息类型和 phase、帧界限、epoch 零值/耗尽、重复与非法转换、确认边界。
- 7449 个跨语言样例：由实际既有 Python MatchControl 生成结果，逐字节比较 C++ 转换分类、控制记录及确认记录。
- Release 与完整 Debug ASan/UBSan 各执行一遍，保留 -g、禁止恢复、帧指针，禁止用 -O1 缩短验证。

尚须实现并验收：原生能力协商、主机命令所有权、带 epoch 的输入准入、帧线程暂停/恢复确认屏障、暂停期间的窗口/心跳/恢复、真实菜单连接、检查点与回放功能对齐。当前产品状态仍为未完成，不能把 codec 验证当成主机暂停或菜单通过。
