// Copyright 2026 Google LLC & Contributors
// 帧同步协议单元测试：验证 protocol.hpp / input_codec 的打包/解包正确性。

#include "frame_sync/protocol.hpp"
#include "frame_sync/input_codec.hpp"

#include <gtest/gtest.h>
#include <cstring>
#include <vector>

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
