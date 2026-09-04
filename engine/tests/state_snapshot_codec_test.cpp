// Copyright 2026 Google LLC & Contributors
// Unit tests for StateSnapshotCodec (ms-17.2)

#include "frame_sync/state_snapshot_codec.hpp"

#include <gtest/gtest.h>
#include <string>

namespace frame_sync {
namespace {

// Test basic compression/decompression
TEST(StateSnapshotCodecTest, BasicRoundtrip) {
  StateSnapshotCodec encoder;
  StateSnapshotCodec decoder;
  
  std::string state1 = "AAAAAAAAAAAAAAAA";  // 16 bytes
  std::string state2 = "BBBBBBBBBBBBBBBB";
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  std::string compressed = encoder.Compress(state2);
  std::string decompressed = decoder.Decompress(compressed);
  
  EXPECT_EQ(decompressed, state2);
}

// Test forced full snapshot
TEST(StateSnapshotCodecTest, ForcedFullSnapshot) {
  StateSnapshotCodec codec;
  
  std::string state1 = "AAAAAAAAAAAAAAAA";
  std::string state2 = "BBBBBBBBBBBBBBBB";
  
  codec.SetBaseline(state1);
  std::string compressed = codec.Compress(state2, true);  // Force full
  
  // Should start with full marker
  EXPECT_EQ(compressed[0], 0x01);
  
  std::string decompressed = codec.Decompress(compressed);
  EXPECT_EQ(decompressed, state2);
}

// Test delta compression
TEST(StateSnapshotCodecTest, DeltaCompression) {
  StateSnapshotCodec encoder;
  StateSnapshotCodec decoder;
  
  std::string state1 = "AAAAAAAAAAAAAAAA";
  std::string state2 = "BBBBBBBBBBBBBBBB";
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  std::string compressed = encoder.Compress(state2, false);  // Delta
  
  // Should start with delta marker
  EXPECT_EQ(compressed[0], 0x00);
  
  std::string decompressed = decoder.Decompress(compressed);
  EXPECT_EQ(decompressed, state2);
}

// Test multi-frame compression
TEST(StateSnapshotCodecTest, MultiFrame) {
  StateSnapshotCodec encoder;
  StateSnapshotCodec decoder;
  
  std::string state1 = "AAAAAAAAAAAAAAAA";
  std::string state2 = "BBBBBBBBBBBBBBBB";
  std::string state3 = "CCCCCCCCCCCCCCCC";
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  
  // Frame 2
  std::string compressed2 = encoder.Compress(state2);
  std::string decompressed2 = decoder.Decompress(compressed2);
  EXPECT_EQ(decompressed2, state2);
  
  // Frame 3
  std::string compressed3 = encoder.Compress(state3);
  std::string decompressed3 = decoder.Decompress(compressed3);
  EXPECT_EQ(decompressed3, state3);
}

// Test compression efficiency
TEST(StateSnapshotCodecTest, CompressionEfficiency) {
  StateSnapshotCodec codec;
  
  std::string state1(10000, 'A');
  std::string state2 = state1;
  state2[5000] = 'B';  // Single byte change
  
  codec.SetBaseline(state1);
  std::string compressed = codec.Compress(state2);
  
  // Delta should be much smaller than full state
  EXPECT_LT(compressed.size(), state1.size() / 2);
}

// Test reset
TEST(StateSnapshotCodecTest, Reset) {
  StateSnapshotCodec codec;
  
  std::string state = "AAAAAAAAAAAAAAAA";
  codec.SetBaseline(state);
  EXPECT_TRUE(codec.HasBaseline());
  
  codec.Reset();
  EXPECT_FALSE(codec.HasBaseline());
}

// Test empty state
TEST(StateSnapshotCodecTest, EmptyState) {
  StateSnapshotCodec codec;
  
  std::string state1;
  std::string state2;
  
  codec.SetBaseline(state1);
  std::string compressed = codec.Compress(state2);
  std::string decompressed = codec.Decompress(compressed);
  
  EXPECT_EQ(decompressed, state2);
}

// Test raw bytes interface
TEST(StateSnapshotCodecTest, RawBytesInterface) {
  StateSnapshotCodec encoder;
  StateSnapshotCodec decoder;
  
  std::string state1 = "Raw bytes test!!";  // 16 chars
  std::string state2 = "Raw bytes new!!!";  // 16 chars
  
  encoder.SetBaseline(reinterpret_cast<const uint8_t*>(state1.data()), state1.size());
  decoder.SetBaseline(reinterpret_cast<const uint8_t*>(state1.data()), state1.size());
  std::string compressed = encoder.Compress(
      reinterpret_cast<const uint8_t*>(state2.data()), state2.size());
  std::string decompressed = decoder.Decompress(compressed, state2.size());
  
  EXPECT_EQ(decompressed, state2);
}

// Test unknown marker
TEST(StateSnapshotCodecTest, UnknownMarker) {
  StateSnapshotCodec codec;
  
  std::string invalid = std::string(1, static_cast<char>(0xFF)) + "data";
  std::string result = codec.Decompress(invalid);
  
  EXPECT_TRUE(result.empty());
}

// Test size mismatch
TEST(StateSnapshotCodecTest, SizeMismatch) {
  StateSnapshotCodec codec;
  
  std::string state1 = "AAAAAAAAAAAAAAAA";
  std::string state2 = "BBBBBBBBBBBBBBBB";
  
  codec.SetBaseline(state1);
  std::string compressed = codec.Compress(state2);
  
  // Wrong expected size
  std::string result = codec.Decompress(compressed, 100);
  EXPECT_TRUE(result.empty());
}

}  // namespace
}  // namespace frame_sync
