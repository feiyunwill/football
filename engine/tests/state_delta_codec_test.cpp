// Copyright 2026 Google LLC & Contributors
// Unit tests for StateDeltaCodec (ms-16.4)

#include "frame_sync/state_delta_codec.hpp"

#include <gtest/gtest.h>
#include <string>

namespace frame_sync {
namespace {

// Test basic encode/decode roundtrip
TEST(StateDeltaCodecTest, BasicRoundtrip) {
  StateDeltaCodec encoder;
  StateDeltaCodec decoder;
  
  std::string state1 = "Hello, World! This is a test state";  // 35 chars
  std::string state2 = "Hello, There! This is a test state";  // 35 chars
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  std::string delta = encoder.EncodeDelta(state2);
  
  EXPECT_FALSE(delta.empty());
  EXPECT_NE(delta, state2);  // Should be compressed
  
  std::string decoded = decoder.DecodeDelta(delta);
  EXPECT_EQ(decoded, state2);
}

// Test with identical frames (no changes)
TEST(StateDeltaCodecTest, IdenticalFrames) {
  StateDeltaCodec codec;
  
  std::string state = "No changes between frames";
  codec.SetBaseline(state);
  
  std::string delta = codec.EncodeDelta(state);
  EXPECT_FALSE(delta.empty());
  
  std::string decoded = codec.DecodeDelta(delta);
  EXPECT_EQ(decoded, state);
}

// Test with many changes
TEST(StateDeltaCodecTest, ManyChanges) {
  StateDeltaCodec encoder;
  StateDeltaCodec decoder;
  
  std::string state1(1000, 'A');
  std::string state2(1000, 'B');
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  std::string delta = encoder.EncodeDelta(state2);
  
  std::string decoded = decoder.DecodeDelta(delta);
  EXPECT_EQ(decoded, state2);
}

// Test with no baseline (should return full state)
TEST(StateDeltaCodecTest, NoBaseline) {
  StateDeltaCodec codec;
  
  std::string state = "State without baseline";
  std::string delta = codec.EncodeDelta(state);
  
  EXPECT_EQ(delta, state);  // Should return full state
}

// Test decode with new codec (should reconstruct correctly)
TEST(StateDeltaCodecTest, DecodeWithNewCodec) {
  StateDeltaCodec codec;
  
  std::string state1 = "First state str";  // 15 chars
  std::string state2 = "Second state st";  // 15 chars
  
  codec.SetBaseline(state1);
  std::string delta = codec.EncodeDelta(state2);
  
  // Create new codec with same baseline
  StateDeltaCodec codec2;
  codec2.SetBaseline(state1);
  std::string decoded = codec2.DecodeDelta(delta);
  
  EXPECT_EQ(decoded, state2);
}

// Test multiple frames
TEST(StateDeltaCodecTest, MultipleFrames) {
  StateDeltaCodec encoder;
  StateDeltaCodec decoder;
  
  std::string state1 = "AAAAAAAAAAAAAAAA";  // 16 chars
  std::string state2 = "BBBBBBBBBBBBBBBB";  // 16 chars
  std::string state3 = "CCCCCCCCCCCCCCCC";  // 16 chars
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  
  std::string delta1 = encoder.EncodeDelta(state2);
  std::string decoded1 = decoder.DecodeDelta(delta1);
  EXPECT_EQ(decoded1, state2);
  
  std::string delta2 = encoder.EncodeDelta(state3);
  std::string decoded2 = decoder.DecodeDelta(delta2);
  EXPECT_EQ(decoded2, state3);
}

// Test compression ratio with sparse changes
TEST(StateDeltaCodecTest, CompressionRatioSparse) {
  StateDeltaCodec codec;
  
  std::string state1(10000, 'A');
  std::string state2 = state1;
  state2[100] = 'B';  // Single change
  
  codec.SetBaseline(state1);
  std::string delta = codec.EncodeDelta(state2);
  
  float ratio = StateDeltaCodec::CompressionRatio(delta.size(), state1.size());
  EXPECT_LT(ratio, 0.1f);  // Should compress well
}

// Test compression ratio with dense changes
TEST(StateDeltaCodecTest, CompressionRatioDense) {
  StateDeltaCodec codec;
  
  std::string state1(1000, 'A');
  std::string state2(1000, 'B');
  
  codec.SetBaseline(state1);
  std::string delta = codec.EncodeDelta(state2);
  
  float ratio = StateDeltaCodec::CompressionRatio(delta.size(), state1.size());
  // Dense changes won't compress as well, but RLE of XOR should still help
  EXPECT_LT(ratio, 0.5f);
}

// Test reset
TEST(StateDeltaCodecTest, Reset) {
  StateDeltaCodec codec;
  
  std::string state = "Test state";
  codec.SetBaseline(state);
  
  EXPECT_TRUE(codec.HasBaseline());
  EXPECT_EQ(codec.GetBaselineSize(), state.size());
  
  codec.Reset();
  
  EXPECT_FALSE(codec.HasBaseline());
  EXPECT_EQ(codec.GetBaselineSize(), 0u);
}

// Test raw bytes interface
TEST(StateDeltaCodecTest, RawBytesInterface) {
  StateDeltaCodec encoder;
  StateDeltaCodec decoder;
  
  std::string state1 = "Raw bytes test!!";  // 16 chars
  std::string state2 = "Raw bytes new!!!";  // 16 chars
  
  encoder.SetBaseline(reinterpret_cast<const uint8_t*>(state1.data()), state1.size());
  decoder.SetBaseline(reinterpret_cast<const uint8_t*>(state1.data()), state1.size());
  std::string delta = encoder.EncodeDelta(reinterpret_cast<const uint8_t*>(state2.data()), state2.size());
  
  std::string decoded = decoder.DecodeDelta(delta);
  EXPECT_EQ(decoded, state2);
}

// Test empty state
TEST(StateDeltaCodecTest, EmptyState) {
  StateDeltaCodec encoder;
  StateDeltaCodec decoder;
  
  std::string state1 = "Init";
  std::string state2 = "Init";
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  std::string delta = encoder.EncodeDelta(state2);
  
  std::string decoded = decoder.DecodeDelta(delta);
  EXPECT_EQ(decoded, state2);
}

// Test RLE compression efficiency
TEST(StateDeltaCodecTest, RLECompression) {
  // Create a pattern that RLE compresses well
  std::string input(1000, 'X');
  std::string compressed = StateDeltaCodec::RLECompress(input);
  
  // RLE should compress this well
  EXPECT_LT(compressed.size(), input.size() / 10);
}

// Test RLE with mixed pattern
TEST(StateDeltaCodecTest, RLEMixedPattern) {
  std::string input;
  for (int i = 0; i < 100; ++i) {
    input.push_back('A');
    input.push_back('B');
    input.push_back('B');
    input.push_back('B');
  }
  
  std::string compressed = StateDeltaCodec::RLECompress(input);
  std::string decompressed = StateDeltaCodec::RLEDecompress(compressed, input.size());
  
  EXPECT_EQ(decompressed, input);
}

// Test size mismatch handling
TEST(StateDeltaCodecTest, SizeMismatch) {
  StateDeltaCodec codec;
  
  std::string state1 = "Short";
  std::string state2 = "Much longer state";
  
  codec.SetBaseline(state1);
  std::string delta = codec.EncodeDelta(state2);
  
  // Should return full state on size mismatch
  EXPECT_EQ(delta, state2);
}

}  // namespace
}  // namespace frame_sync
