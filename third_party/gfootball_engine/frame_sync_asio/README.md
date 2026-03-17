# Frame Sync C++ 服务器 / 客户端 (Boost.Asio)

与 Python 版协议兼容的 C++ 网络实现，仅依赖 Boost.Asio（无引擎、无 OpenGL/SDL）。

## 构建（独立，仅需 Boost）

```bash
# 在引擎目录下
cd third_party/gfootball_engine
cmake -S frame_sync_asio -B build_fs_asio -DBoost_ROOT=/path/to/boost  # 如需要指定 Boost
cmake --build build_fs_asio
```

产物：`build_fs_asio/frame_sync_server`、`build_fs_asio/frame_sync_client`。

若已配置完整引擎构建（含 Boost），也可在引擎 CMake 中直接生成上述两可执行文件（见根 CMakeLists.txt 末尾）。

## 运行

**服务器**

```bash
./frame_sync_server [port] [left_agents] [right_agents] [seed]
# 默认: port=12345, left=1, right=1, seed=42
```

**客户端**

```bash
./frame_sync_client <host> <port> [slot_index]
# 例: ./frame_sync_client 127.0.0.1 12345 0
```

## 协议说明

- 连接后服务器下发 `SessionStart`（seed, left_agents, right_agents）与 `SlotAssignment`（本端控制的 slot 列表）。
- 客户端回复 `Ready` 后，服务器开始帧循环。
- 每帧：客户端发 `FrameInput`（frame_id + 己方 slot 输入），服务器汇总（超时用默认输入）后广播 `AuthoritativeFrame`。
- 本实现为**纯网络**：服务器不跑引擎，仅做输入汇总与广播；各端用收到的权威输入在本地做确定性步进即可。
