# Phase 18: 多房间/大厅系统

## 目标
实现房间创建、加入、大厅聊天，支持多人联机对战。

## 架构
```
Client → Lobby Server (TCP)
              ├── 房间列表查询
              ├── 创建房间
              ├── 加入房间
              └── 聊天消息
              
Game Server (TCP, 每房间独立进程)
              ├── 帧同步逻辑（已有 integrated_server）
              └── 玩家连接
```

简化方案：Lobby Server 管理房间元数据，Game Server 是独立进程。客户端从 Lobby 获取房间地址后直连 Game Server。

## Milestones

### ms-18.1: 大厅协议与房间元数据
- 定义 LobbyMessageType（CreateRoom/JoinRoom/LeaveRoom/RoomList/Chat/RoomInfo）
- RoomMetadata 结构：room_id, name, scenario, seed, max_players, player_count, status, address
- 纯头文件库，无服务器依赖，可独立测试

### ms-18.2: 房间管理器
- RoomManager 类：创建/加入/离开/查询房间
- 房间状态机：Waiting → Playing → Finished
- 玩家列表管理，ready 状态跟踪
- 房间 ID 生成（随机 32-bit）

### ms-18.3: Lobby 服务器
- TCP 服务器，接收客户端 lobby 请求
- 广播房间列表变更
- 聊天消息转发
- 与 Game Server 进程通信（通过房间元数据中的地址）

### ms-18.4: 客户端大厅集成
- LobbyClient 类：连接 lobby 服务器，发送请求，接收更新
- 文本界面：显示房间列表、创建/加入房间、聊天
- 集成到 integrated_client.cpp（启动时先连 lobby）

### ms-18.5: 端到端测试
- 启动 lobby server + 多个 game server
- 多个客户端连接 lobby → 创建/加入房间 → 开始游戏
- 验证房间状态同步、聊天消息、观战者加入
