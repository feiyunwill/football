// Copyright 2026 Google LLC & Contributors
// Phase 5 tests: reconnection, jitter stats, delta compression.

#include "frame_sync/protocol.hpp"
#include "frame_sync/engine_integration.hpp"
#include "frame_sync/jitter_stats.hpp"
#include "frame_sync/state_compression.hpp"
#include "frame_sync/client_state.hpp"

#include <gtest/gtest.h>
#include <cmath>
#include <vector>

using namespace frame_sync;

// ===== JitterStats Tests =====

TEST(JitterStatsTest, InitialState) {
  JitterStats stats;
  EXPECT_EQ(stats.total_frames, 0);
  EXPECT_EQ(stats.received_frames, 0);
  EXPECT_EQ(stats.lost_frames, 0);
  EXPECT_FLOAT_EQ(stats.loss_rate, 0.0f);
  EXPECT_DOUBLE_EQ(stats.jitter_ms, 0.0);
}

TEST(JitterStatsTest, RecordArrival) {
  JitterStats stats;
  stats.record_arrival(100.0);
  stats.record_arrival(110.0);
  stats.record_arrival(130.0);  // 20ms interval (jitter)
  stats.record_arrival(140.0);  // 10ms interval

  EXPECT_EQ(stats.received_frames, 4);
  EXPECT_GE(stats.jitter_ms, 0.0);  // jitter computed from intervals
}

TEST(JitterStatsTest, LossRate) {
  JitterStats stats;
  stats.record_arrival(100.0);
  stats.record_lost();  // frame lost
  stats.record_arrival(120.0);

  EXPECT_EQ(stats.total_frames, 3);
  EXPECT_EQ(stats.received_frames, 2);
  EXPECT_EQ(stats.lost_frames, 1);
  EXPECT_FLOAT_EQ(stats.loss_rate, 1.0f / 3.0f);
}

TEST(JitterStatsTest, RTTTracking) {
  JitterStats stats;
  stats.record_rtt(10.0);
  stats.record_rtt(20.0);
  stats.record_rtt(30.0);

  EXPECT_DOUBLE_EQ(stats.avg_rtt_ms, 20.0);
  EXPECT_DOUBLE_EQ(stats.max_rtt_ms, 30.0);
}

TEST(JitterStatsTest, RecommendedBufferSize) {
  JitterStats stats;
  // With 0 jitter, should recommend minimum buffer
  EXPECT_GE(stats.recommended_buffer_frames, 2);

  // High jitter should recommend larger buffer
  for (int i = 0; i < 50; ++i) {
    stats.record_arrival(100.0 + i * 100 + (i % 3) * 50);  // variable intervals
  }
  EXPECT_GE(stats.recommended_buffer_frames, 2);
}

// ===== DeltaSlotInput Tests =====

TEST(DeltaSlotInputTest, NoChange) {
  SlotInput prev{1.0f, 2.0f, 0x00FF};
  SlotInput curr{1.0f, 2.0f, 0x00FF};

  DeltaSlotInput delta = DeltaSlotInput::Compute(curr, prev);
  EXPECT_TRUE(delta.is_empty());

  // Pack/unpack round-trip
  uint8_t buf[16];
  size_t n = delta.Pack(buf, sizeof(buf));
  EXPECT_EQ(n, 1u);  // just flags byte

  DeltaSlotInput decoded;
  size_t used = decoded.Unpack(buf, n);
  EXPECT_EQ(used, n);
  SlotInput reconstructed = decoded.Apply(prev);
  EXPECT_FLOAT_EQ(reconstructed.dir_x, prev.dir_x);
  EXPECT_FLOAT_EQ(reconstructed.dir_y, prev.dir_y);
  EXPECT_EQ(reconstructed.buttons, prev.buttons);
}

TEST(DeltaSlotInputTest, AllFieldsChanged) {
  SlotInput prev{1.0f, 2.0f, 0x00FF};
  SlotInput curr{3.0f, 4.0f, 0x0000};

  DeltaSlotInput delta = DeltaSlotInput::Compute(curr, prev);
  EXPECT_EQ(delta.flags, 0x07);  // all 3 bits set
  EXPECT_FALSE(delta.is_empty());
  EXPECT_EQ(delta.packed_size(), 11u);  // 1 + 4 + 4 + 2

  // Pack/unpack round-trip
  uint8_t buf[16];
  size_t n = delta.Pack(buf, sizeof(buf));
  EXPECT_EQ(n, 11u);

  DeltaSlotInput decoded;
  size_t used = decoded.Unpack(buf, n);
  EXPECT_EQ(used, 11u);
  SlotInput reconstructed = decoded.Apply(prev);
  EXPECT_FLOAT_EQ(reconstructed.dir_x, 3.0f);
  EXPECT_FLOAT_EQ(reconstructed.dir_y, 4.0f);
  EXPECT_EQ(reconstructed.buttons, 0x0000);
}

TEST(DeltaSlotInputTest, PartialChange) {
  SlotInput prev{1.0f, 2.0f, 0x00FF};
  SlotInput curr{1.0f, 5.0f, 0x00FF};  // only dir_y changed

  DeltaSlotInput delta = DeltaSlotInput::Compute(curr, prev);
  EXPECT_EQ(delta.flags, 0x02);  // only bit 1
  EXPECT_EQ(delta.packed_size(), 5u);  // 1 + 4

  uint8_t buf[16];
  size_t n = delta.Pack(buf, sizeof(buf));
  EXPECT_EQ(n, 5u);

  DeltaSlotInput decoded;
  decoded.Unpack(buf, n);
  SlotInput reconstructed = decoded.Apply(prev);
  EXPECT_FLOAT_EQ(reconstructed.dir_x, 1.0f);  // unchanged
  EXPECT_FLOAT_EQ(reconstructed.dir_y, 5.0f);  // changed
  EXPECT_EQ(reconstructed.buttons, 0x00FF);  // unchanged
}

TEST(DeltaSlotInputTest, CompressionRatio) {
  SlotInput prev{1.0f, 2.0f, 0x00FF};
  // 10 frames with small changes
  size_t total_delta = 0;
  for (int i = 0; i < 10; ++i) {
    SlotInput curr{1.0f, static_cast<float>(2.0f + i * 0.1f), 0x00FF};
    DeltaSlotInput delta = DeltaSlotInput::Compute(curr, prev);
    total_delta += delta.packed_size();
    prev = curr;
  }

  size_t total_full = 10 * SLOT_INPUT_BYTES;
  float ratio = static_cast<float>(total_delta) / total_full;
  EXPECT_LT(ratio, 1.0f);  // delta should be smaller
}

// ===== DeltaEncoder Tests =====

TEST(DeltaEncoderTest, EncodeDecode) {
  DeltaEncoder encoder(2);

  std::vector<SlotInput> frame1 = {{1.0f, 0.0f, 0}, {0.0f, 1.0f, 0}};
  auto deltas = encoder.Encode(frame1);
  EXPECT_EQ(deltas.size(), 2u);

  auto decoded = encoder.Decode(deltas);
  EXPECT_EQ(decoded.size(), 2u);
  EXPECT_FLOAT_EQ(decoded[0].dir_x, 1.0f);
  EXPECT_FLOAT_EQ(decoded[1].dir_y, 1.0f);
}

TEST(DeltaEncoderTest, MultiFrameCompression) {
  DeltaEncoder encoder(1);

  // 20 frames: same dir_x, slowly changing dir_y
  size_t total_delta = 0;
  for (int i = 0; i < 20; ++i) {
    std::vector<SlotInput> current = {{1.0f, static_cast<float>(i * 0.1f), 0}};
    auto deltas = encoder.Encode(current);
    total_delta += deltas[0].packed_size();
    encoder.Decode(deltas);  // advance state
  }

  size_t total_full = 20 * SLOT_INPUT_BYTES;
  float ratio = static_cast<float>(total_delta) / total_full;
  EXPECT_LE(ratio, 0.5f);  // should compress to <= 50% (only dir_y changes)
}
