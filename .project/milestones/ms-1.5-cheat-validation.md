# ms-1.5: 外挂校验

## 基本信息

- **ID**: ms-1.5
- **标题**: 外挂校验
- **阶段**: Phase 1
- **优先级**: 高
- **状态**: COMPLETED

## 目标

实现服务器端输入合法性验证，拒绝非法输入。

## 成功条件

- [x] 服务器验证输入合法性
- [x] 拒绝非法输入
- [x] 防止作弊行为

## 实现细节

### 验证内容

1. **方向范围验证**：dir_x, dir_y 必须在 [-1, 1] 范围内
2. **NaN/Inf 检查**：拒绝非数值输入
3. **按钮位掩码验证**：只允许有效的按钮位（0-11）
4. **槽位所有权检查**：客户端只能写入自己分配的槽位

### 文件变更

| 文件 | 变更 |
|------|------|
| `engine/src/frame_sync/protocol.hpp` | 新增 `IsValidSlotInput()` 函数 |
| `engine/src/frame_sync/asio_server.cpp` | 添加所有权检查 + 输入验证 |
| `engine/src/frame_sync/asio_server_udp.cpp` | 添加所有权检查 + 输入验证 |
| `engine/src/frame_sync/asio_server_engine.cpp` | 添加所有权检查 + 输入验证 |
| `engine/src/frame_sync/integrated_server.cpp` | 添加所有权检查 + 输入验证 |
| `gfootball/frame_sync/protocol.py` | 新增 `is_valid_slot_input()` 函数 |
| `gfootball/frame_sync/server.py` | 添加输入验证 |
| `gfootball/frame_sync/server_async.py` | 添加输入验证 |

## 进度

- **开始时间**: 2026-08-31
- **实际完成**: 2026-08-31
- **完成百分比**: 100%
