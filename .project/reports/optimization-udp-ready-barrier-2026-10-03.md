# UDP 开赛 Ready 屏障修复（2026-10-03）

产品 UDP 握手在两名已分配玩家之外暂留两个未分配槽位的临时会话。`InitialReadyLocked()` 原先要求这些临时会话也进入 `Streaming`，导致真实玩家 Ready 后仍等待约 30 秒，直到临时会话超时清理。16 秒的接管验收因开赛前没有足够权威帧而失败。

现在 Ready 屏障只等待已分配槽位的会话，同时继续等待已分配但未进入 `Streaming` 的玩家。隔离对照中，原始 UDP 接管场景从 16 秒内无法开赛，变为约 4.35 秒完成开赛、断线接管及后续 151 帧。

完整 `.project/checks/ai_tactics_contract.py --suite integration` 通过：Release 与 Sanitizer 构建、真实 TCP/UDP 接管、原生客户端、控制边界和跨构建权威回放共 32 组结果、161,788 条断言。验收结果入库于 `.project/optimization/evidence/udp_ready_barrier_20261003.json`。
