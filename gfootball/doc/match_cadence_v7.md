# 比赛 v7：50Hz 输入与物理节拍

2026-09-13。Python Local、Host、Join 和比赛回放使用下列唯一支持的契约。比赛握手、恢复原点、Ready 确认和持久存档都验证同一组参数。

| 字段 | 值 | 含义 |
| --- | --- | --- |
| `input_hz` | 50 | 每秒名义模拟时间采样50帧输入 |
| `network_hz` | 50 | 每秒名义模拟时间生成50个权威帧 |
| `physics_steps` | 2 | 每个权威帧推进两个原生物理步 |
| `physics_step_us` | 10000 | 单个物理步10ms |

名义一帧20ms，物理频率保持100Hz。绝对截止时刻调度会跳过已错过的墙钟机会，模拟帧号和输入序列仍连续。暂停期间不推进比赛，恢复沿用已有控制代次和中性输入屏障。离线推进或回放不受墙钟速率限制。

比赛场景原有 `game_duration` 按10Hz计数。创建新比赛引擎时进行一次整数换算：3000→15000帧、400→2000帧；超出原生有符号整数范围则在创建 GameEnv 前拒绝。原场景文件和旧通用接口保持原有定义。终止仍使用引擎原有进行中步数，开场动画不会据此被当成有效比赛时长。AI 接管的射门／解围冷却分别保持3／4秒模拟时间。

## 协议与存档

- 比赛协商版本7，快照魔数 `FMATCH7\0`；v6及其10Hz节拍不能获得v7比赛槽位。
- MatchReady 保持17字节、小端格式 `<BHHHHII`；epoch=0 的独立字节向量为 `12 0700 3200 3200 0200 10270000 00000000`。
- 原点继续携带 settings、identity、sha256、digest、cadence、control；暂停消息和输入代次的语义保持一致。
- checkpoint 升至3，增加必需的 cadence 元数据。v1/v2存档、缺失或不一致节拍会在快照解码和引擎构造前被拒绝，没有自动迁移。
- 回放文件容器格式保持原有版本，header.tick_hz=50，结束时间戳为已录帧数×20ms。回放原点采用checkpoint v3。
- 原生比赛身份为 `gfootball.GameEnv.FSTA2.match1.physics2.cadence50`；资源与实际加载二进制的指纹仍参与恢复校验。

通用 Python v2/v3 接口及通用 FramePacer 默认仍为10Hz。C++ 三个独立入口当前仍使用原生 v2／10Hz，消息15与Python比赛协议含义不同；本轮没有实现跨这两个协议族的互通。

## 验证与后续

使用当前 Release 引擎完成402项比赛／图形检查和123项通用接口检查，均无跳过。覆盖实际 GameEnv、TCP／UDP、暂停恢复、结束确认、真实 SDL/OpenGL 展示及持久回放。新增的10项产品节拍检查包含在402项中，另有一次独立执行；不重复累计。

详见[实施与证据](../../.project/reports/optimization-product-cadence-v7-2026-09-13.md)。50Hz准入并不等同于真实设备到球员动作的50ms延迟验收；原生入口节拍、广域网条件、长期性能与消毒器下的完整v7链路仍须继续验证。

```bash
LD_LIBRARY_PATH=/tmp/football-optimization-native \
GFOOTBALL_DATA_DIR="$PWD/engine/data" SDL_VIDEODRIVER=offscreen \
python .project/checks/frame_replay_probe.py --match --multiplayer --udp-multiplayer --graphics --native --output <全新目录>
```
