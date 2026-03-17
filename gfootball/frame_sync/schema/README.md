# 帧同步协议 Schema

总览见：** [帧同步：协议描述与配置集中](../../doc/frame_sync_protocol_and_config.md) **。

## 常量单一来源

- **constants.yaml**：帧超时与预测保底等常量的单一来源。
- **generate_config.py**：根据 `constants.yaml` 生成 `../config.py`（需安装 `pyyaml`：`pip install pyyaml`）。  
  修改 YAML 后执行：`python -m gfootball.frame_sync.schema.generate_config`
- **C++**：`third_party/gfootball_engine/src/frame_sync/protocol.hpp` 中的同名常量需与 YAML 保持一致，目前为手动同步。

## 后续：消息格式代码生成

完整协议（MessageType、SlotInput 布局、pack/unpack）的单一来源与 C++/Python 代码生成可在此基础上扩展（如 Protobuf 或自定义 DSL）。
