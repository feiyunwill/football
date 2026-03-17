# Copyright 2019 Google LLC
# 帧同步配置集中：超时与预测保底等常量（与 C++ protocol.hpp 保持一致，参见 CXX_STANDARD / PROTOCOL.md）

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# ----- 超时 -----
# 服务器等待该帧各客户端输入的最长时间（毫秒）
FRAME_INPUT_TIMEOUT_MS = 200

# ----- 预测保底（可调） -----
# 客户端最多超前已确认权威帧的帧数；超过则本帧不预测，等待权威
MAX_PREDICT_AHEAD_FRAMES = 3
# 连续多少帧未收到任何服务器包则进入「仅等权威」模式，停止预测
MAX_FRAMES_WITHOUT_PACKET = 5
# 状态校验：每 K 帧服务器下发一次 state hash，客户端比对
STATE_HASH_INTERVAL_K = 10
