# Phase 17: 网络优化与观战系统

## 目标
提升网络对战体验，添加观战和回放功能。

## Milestones

### ms-17.1: 延迟补偿
- 输入时间戳校正：客户端发送输入时附带本地时间戳
- 服务器根据 RTT 调整输入应用时机
- 客户端预测时考虑网络延迟

### ms-17.2: 状态快照压缩传输
- 使用 StateDeltaCodec 压缩全量状态快照
- 仅在关键帧（每 N 帧）发送全量快照
- 中间帧使用 delta 压缩

### ms-17.3: 观战模式
- 添加观战者角色（只读，不发送输入）
- 观战者接收所有玩家的 authoritative frames
- 支持多个观战者同时连接

### ms-17.4: 回放系统集成
- 将 ReplayRecorder 接入 IntegratedFrameSyncClient
- 游戏结束后自动保存回放
- 添加回放播放界面

### ms-17.5: 网络诊断工具
- 实时显示 RTT/jitter/丢包/预测准确率
- 网络质量等级指示器
- 延迟补偿可视化

## 技术要点
- 延迟补偿需要服务器支持时间戳校正
- 状态压缩可复用 ms-16.4 的 StateDeltaCodec
- 观战模式需要新的 MessageType（SpectatorJoin）
- 回放保存路径：`replays/` 目录
- 诊断信息通过 overlay UI 显示
