// Copyright 2026 Google LLC & Contributors
// 帧同步协议单元测试：验证 protocol.hpp / input_codec 的打包/解包正确性。
// 2026-08-30 新增：客户端预测/回滚集成测试。

#include "frame_sync/protocol.hpp"
#include "frame_sync/input_codec.hpp"
#include "frame_sync/client_state.hpp"

#include <gtest/gtest.h>
#include <cstring>
#include <vector>
#include <unordered_map>

using namespace frame_sync;

// ===== SlotInput =====

TEST(SlotInputTest, DefaultConstruction) {
  SlotInput s = SlotInput::Default();
  EXPECT_FLOAT_EQ(s.dir_x, 0.f);
  EXPECT_FLOAT_EQ(s.dir_y, 0.f);
  EXPECT_EQ(s.buttons, 0);
}

TEST(SlotInputTest, Equality) {
  SlotInput a{1.0f, -0.5f, 0b1010};
  SlotInput b{1.0f, -0.5f, 0b1010};
  SlotInput c{1.0f, -0.5f, 0b1011};
  EXPECT_EQ(a, b);
  EXPECT_NE(a, c);
}

TEST(SlotInputTest, BinaryLayoutSize) {
  // 2026-08-28 修复后：SLOT_INPUT_BYTES = 10，与 Python 一致
  EXPECT_EQ(SLOT_INPUT_BYTES, 10u);
  EXPECT_EQ(sizeof(SlotInput), 10u);
}

TEST(SlotInputTest, MemcpyRoundTrip) {
  SlotInput original{3.14f, -2.71f, 0xABCD};
  char buf[SLOT_INPUT_BYTES];
  std::memcpy(buf, &original, SLOT_INPUT_BYTES);

  SlotInput decoded;
  std::memcpy(&decoded, buf, SLOT_INPUT_BYTES);

  EXPECT_FLOAT_EQ(decoded.dir_x, original.dir_x);
  EXPECT_FLOAT_EQ(decoded.dir_y, original.dir_y);
  EXPECT_EQ(decoded.buttons, original.buttons);
}

// ===== MessageType =====

TEST(MessageTypeTest, UniqueValues) {
  // 所有消息类型值必须唯一且在 uint8 范围内
  std::vector<uint8_t> values = {
      static_cast<uint8_t>(MessageType::Connect),
      static_cast<uint8_t>(MessageType::Disconnect),
      static_cast<uint8_t>(MessageType::FrameInput),
      static_cast<uint8_t>(MessageType::AuthoritativeFrame),
      static_cast<uint8_t>(MessageType::StateHash),
      static_cast<uint8_t>(MessageType::SessionStart),
      static_cast<uint8_t>(MessageType::Ready),
      static_cast<uint8_t>(MessageType::SlotAssignment),
      static_cast<uint8_t>(MessageType::Heartbeat),
  };

  EXPECT_EQ(values.size(), 9u);

  // 检查唯一性
  std::sort(values.begin(), values.end());
  auto last = std::unique(values.begin(), values.end());
  EXPECT_EQ(last, values.end()) << "Duplicate MessageType values found";

  // 检查范围
  for (auto v : values) {
    EXPECT_LE(v, 255u);
  }
}

// ===== Heartbeat 常量 =====

TEST(ProtocolConstantsTest, HeartbeatPacketSize) {
  // 1 (msg_type) + 4 (frame_id) + 4 (timestamp) = 9
  EXPECT_EQ(HEARTBEAT_PACKET_BYTES, 9u);
}

TEST(ProtocolConstantsTest, TimeoutConstants) {
  EXPECT_EQ(FRAME_INPUT_TIMEOUT_MS, 200);
  EXPECT_EQ(MAX_PREDICT_AHEAD_FRAMES, 3);
  EXPECT_EQ(MAX_FRAMES_WITHOUT_PACKET, 5);
  EXPECT_EQ(STATE_HASH_INTERVAL_K, 10);
}

// ===== AuthoritativeFrame 布局 =====

TEST(AuthoritativeFrameTest, HeaderSize) {
  // 1 (msg_type) + 4 (frame_id) + 2 (num_slots) = 7
  EXPECT_EQ(AUTHORITATIVE_FRAME_HEADER_BYTES, 7u);
}

// ===== ClientFrameInput 布局 =====

TEST(ClientFrameInputTest, HeaderSize) {
  // 1 (msg_type) + sizeof(ClientFrameInputHeader)
  // ClientFrameInputHeader = frame_id(4) + num_slots(2) = 6
  // 但含 msg_type 的常量 = 1 + sizeof(ClientFrameInputHeader) = 7
  // 实际 sizeof 可能有 padding，用 sizeof 验证
  EXPECT_EQ(CLIENT_FRAME_INPUT_HEADER_BYTES, 1u + sizeof(ClientFrameInputHeader));
}

TEST(ClientFrameInputTest, SlotEntrySize) {
  // 2 (slot_index) + sizeof(SlotInput)
  EXPECT_EQ(CLIENT_SLOT_ENTRY_BYTES, sizeof(uint16_t) + SLOT_INPUT_BYTES);
}

// ===== SessionStart 布局 =====

TEST(SessionStartTest, ParamsSize) {
  // 4 (seed) + 2 (left) + 2 (right) = 8
  EXPECT_EQ(SESSION_START_PARAMS_BYTES, 8u);
}

// ===== 指针布局验证 =====

TEST(LayoutTest, SlotInputNoPadding) {
  // 2026-08-28 修复：#pragma pack(push, 1) 消除 padding
  // sizeof(SlotInput) = 10 = 4 + 4 + 2，与 Python struct.pack('<ffH') 一致
  EXPECT_EQ(sizeof(SlotInput), 10u);
  EXPECT_EQ(SLOT_INPUT_BYTES, 10u);
  EXPECT_EQ(sizeof(SlotInput::dir_x), 4u);
  EXPECT_EQ(sizeof(SlotInput::dir_y), 4u);
  EXPECT_EQ(sizeof(SlotInput::buttons), 2u);
}

// ===== 帧 ID 类型 =====

TEST(TypesTest, FrameIdIsUint32) {
  frame_id_t id = 0xFFFFFFFF;
  EXPECT_EQ(id, 4294967295u);
}

TEST(TypesTest, StateHashIsUint64) {
  state_hash_t h = 0xFFFFFFFFFFFFFFFFULL;
  EXPECT_EQ(h, 18446744073709551615ULL);
}

// ===== 客户端预测/回滚集成测试 =====

// Minimal fake engine for testing prediction/rollback.
struct FakeGameEngine {
  float position = 0.0f;  // simulated ball position
  int step_count = 0;
  std::vector<SlotInput> applied_inputs;

  StateBlob save() {
    StateBlob blob(sizeof(float) + sizeof(int));
    std::memcpy(blob.data(), &position, sizeof(float));
    std::memcpy(blob.data() + sizeof(float), &step_count, sizeof(int));
    return blob;
  }

  void restore(const StateBlob& blob) {
    ASSERT_EQ(blob.size(), sizeof(float) + sizeof(int));
    std::memcpy(&position, blob.data(), sizeof(float));
    std::memcpy(&step_count, blob.data() + sizeof(float), sizeof(int));
  }

  void step(const SlotInput& input) {
    position += input.dir_x;  // simple: position += direction
    ++step_count;
    applied_inputs.push_back(input);
  }

  void reset() {
    position = 0.0f;
    step_count = 0;
    applied_inputs.clear();
  }
};

TEST(PredictionRollbackTest, PredictThenRollback) {
  FakeGameEngine engine;
  ClientState cs(8);
  frame_id_t frame = 0;

  // Predict frames 0-3 with direction=1.0
  SlotInput predicted;
  predicted.dir_x = 1.0f;

  for (int i = 0; i < 4; ++i) {
    cs.save_snapshot(frame, predicted, [&]() { return engine.save(); });
    engine.step(predicted);
    ++frame;
  }
  EXPECT_EQ(engine.position, 4.0f);  // 0 + 1*4
  EXPECT_EQ(engine.step_count, 4);

  // Server sends authoritative frame 2 with direction=10.0 (different)
  SlotInput auth;
  auth.dir_x = 10.0f;

  bool ok = cs.rollback_to(2, auth,
                           [&](const StateBlob& b) { engine.restore(b); },
                           [&](const SlotInput& i) { engine.step(i); });

  EXPECT_TRUE(ok);
  // Restored to frame 2 state (position=2.0, step_count=2), then stepped once with auth
  EXPECT_FLOAT_EQ(engine.position, 12.0f);  // 2.0 + 10.0
  EXPECT_EQ(engine.step_count, 3);
  EXPECT_EQ(cs.rollback_count(), 1);
}

TEST(PredictionRollbackTest, PredictWithNoRollback) {
  FakeGameEngine engine;
  ClientState cs(8);
  frame_id_t frame = 0;

  // Predict frames 0-2 with direction=1.0
  SlotInput predicted;
  predicted.dir_x = 1.0f;

  for (int i = 0; i < 3; ++i) {
    cs.save_snapshot(frame, predicted, [&]() { return engine.save(); });
    engine.step(predicted);
    ++frame;
  }

  // Server confirms frame 0 with same input — no rollback needed
  SlotInput auth = predicted;
  bool ok = cs.rollback_to(0, auth,
                           [&](const StateBlob& b) { engine.restore(b); },
                           [&](const SlotInput& i) { engine.step(i); });

  EXPECT_TRUE(ok);
  // Restored to frame 0 (position=0, step=0), stepped once
  EXPECT_FLOAT_EQ(engine.position, 1.0f);
  EXPECT_EQ(cs.rollback_count(), 1);  // still counts as rollback
}

TEST(PredictionRollbackTest, EvictionPreventsStaleRollback) {
  FakeGameEngine engine;
  ClientState cs(4);  // small buffer
  frame_id_t frame = 0;

  SlotInput input;
  input.dir_x = 1.0f;

  // Fill and overflow the buffer
  for (int i = 0; i < 8; ++i) {
    cs.save_snapshot(frame + i, input, [&]() { return engine.save(); });
    engine.step(input);
  }

  // Buffer should only hold 4 entries
  EXPECT_EQ(cs.buffer_size(), 4);

  // Trying to rollback to frame 0 should fail (evicted)
  bool ok = cs.rollback_to(0, input,
                           [&](const StateBlob& b) { engine.restore(b); },
                           [&](const SlotInput& i) { engine.step(i); });
  EXPECT_FALSE(ok);
}

TEST(PredictionRollbackTest, StateHashVerification) {
  ClientState cs(8);

  // Server sends hash for frame 10
  cs.record_server_hash(10, 0xABCDEF0123456789ULL);

  EXPECT_EQ(cs.check_hash(10, 0xABCDEF0123456789ULL),
            ClientState::HashCheck::kMatch);
  EXPECT_EQ(cs.check_hash(10, 0x1111111111111111ULL),
            ClientState::HashCheck::kMismatch);
  EXPECT_EQ(cs.check_hash(5, 0xABCDEF0123456789ULL),
            ClientState::HashCheck::kUnknown);
}
