# 帧同步：协议描述与配置集中

本文档说明帧同步的**协议描述**、**常量/超时配置集中**与**代码生成**的现状与用法。

---

## 1. 帧同步常量 / 超时配置集中

### 1.1 设计

- **单一来源**：`gfootball/frame_sync/schema/constants.yaml` 定义以下常量（与 C++ `protocol.hpp` 语义一致）：
  - `frame_input_timeout_ms`：服务器等待该帧各客户端输入的最长时间（毫秒）
  - `max_predict_ahead_frames`：客户端最多超前已确认权威帧的帧数
  - `max_frames_without_packet`：连续多少帧未收到服务器包则停止预测、仅等权威
  - `state_hash_interval_k`：每 K 帧服务器下发一次 state hash，客户端比对

- **Python 侧**：由 YAML 生成 `gfootball/frame_sync/config.py`，其它代码从 `config` 或 `protocol` 导入。
- **C++ 侧**：`third_party/gfootball_engine/src/frame_sync/protocol.hpp` 中同名常量需与 YAML 保持一致，**目前为手动同步**。

### 1.2 使用

| 操作 | 命令或位置 |
|------|------------|
| 修改常量 | 编辑 `gfootball/frame_sync/schema/constants.yaml` |
| 生成 Python config | `python -m gfootball.frame_sync.schema.generate_config`（需 `pip install pyyaml`） |
| Python 使用 | `from gfootball.frame_sync.config import FRAME_INPUT_TIMEOUT_MS, ...` 或 `from gfootball.frame_sync.protocol import FRAME_INPUT_TIMEOUT_MS, ...` |
| C++ 同步 | 修改 YAML 后，手动改 `protocol.hpp` 中 `FRAME_INPUT_TIMEOUT_MS`、`MAX_PREDICT_AHEAD_FRAMES`、`MAX_FRAMES_WITHOUT_PACKET`、`STATE_HASH_INTERVAL_K` |

### 1.3 文件关系

```
schema/constants.yaml     →  generate_config.py  →  frame_sync/config.py
                                                          ↑
frame_sync/protocol.py  ← 从 config 导入并再导出（向后兼容）
C++ protocol.hpp        ← 手动与 constants.yaml 保持一致
```

---

## 2. 协议描述与代码生成

### 2.1 当前状态

- **常量**：已有 YAML 描述 + 生成 `config.py`（见上文）。
- **消息格式**：`MessageType`、`SlotInput` 布局、各消息的 pack/unpack 仍**手写**在：
  - Python：`gfootball/frame_sync/protocol.py`
  - C++：`third_party/gfootball_engine/src/frame_sync/protocol.hpp`、`protocol_io.hpp` 等

两边需人工保证格式一致（注释与 PROTOCOL.md 已说明对齐关系）。

### 2.2 后续可选扩展

将完整协议（消息类型、字段布局、pack/unpack）做成单一描述并生成 Python/C++ 代码，例如：

- 用 Protobuf 定义消息，生成序列化代码；
- 或自定义 DSL（如 YAML/JSON schema）配合代码生成脚本生成 `protocol.py` 与 C++ 的 pack/unpack。

详见 `gfootball/frame_sync/schema/README.md`。

---

## 3. 相关文件速查

| 文件 | 作用 |
|------|------|
| `gfootball/frame_sync/schema/constants.yaml` | 常量单一来源 |
| `gfootball/frame_sync/schema/generate_config.py` | 根据 YAML 生成 `config.py` |
| `gfootball/frame_sync/config.py` | 生成的 Python 常量（或手写，若未跑生成脚本） |
| `gfootball/frame_sync/protocol.py` | Python 协议：MessageType、SlotInput、pack/unpack，从 config 导入常量 |
| `third_party/gfootball_engine/src/frame_sync/protocol.hpp` | C++ 常量与协议定义 |
| `third_party/gfootball_engine/src/frame_sync/PROTOCOL.md` | 帧同步协议行为说明 |
