// Copyright 2026 Google LLC & Contributors
// Tests for frame sync interpolator and protocol_io.

#include "frame_sync/interpolator.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/state_compression.hpp"
#include <gtest/gtest.h>
#include <cmath>

using namespace frame_sync;

// ===== Vec3 Tests =====

TEST(Vec3Test, DefaultConstruction) {
  Vec3 v;
  EXPECT_FLOAT_EQ(v.x, 0.f);
  EXPECT_FLOAT_EQ(v.y, 0.f);
  EXPECT_FLOAT_EQ(v.z, 0.f);
}

TEST(Vec3Test, ParameterizedConstruction) {
  Vec3 v(1.f, 2.f, 3.f);
  EXPECT_FLOAT_EQ(v.x, 1.f);
  EXPECT_FLOAT_EQ(v.y, 2.f);
  EXPECT_FLOAT_EQ(v.z, 3.f);
}

TEST(Vec3Test, Addition) {
  Vec3 a(1.f, 2.f, 3.f);
  Vec3 b(4.f, 5.f, 6.f);
  Vec3 result = a + b;
  EXPECT_FLOAT_EQ(result.x, 5.f);
  EXPECT_FLOAT_EQ(result.y, 7.f);
  EXPECT_FLOAT_EQ(result.z, 9.f);
}

TEST(Vec3Test, Subtraction) {
  Vec3 a(4.f, 5.f, 6.f);
  Vec3 b(1.f, 2.f, 3.f);
  Vec3 result = a - b;
  EXPECT_FLOAT_EQ(result.x, 3.f);
  EXPECT_FLOAT_EQ(result.y, 3.f);
  EXPECT_FLOAT_EQ(result.z, 3.f);
}

TEST(Vec3Test, ScalarMultiply) {
  Vec3 v(1.f, 2.f, 3.f);
  Vec3 result = v * 2.f;
  EXPECT_FLOAT_EQ(result.x, 2.f);
  EXPECT_FLOAT_EQ(result.y, 4.f);
  EXPECT_FLOAT_EQ(result.z, 6.f);
}

TEST(Vec3Test, Length) {
  Vec3 v(3.f, 4.f, 0.f);
  EXPECT_FLOAT_EQ(v.length(), 5.f);
}

TEST(Vec3Test, LengthSquared) {
  Vec3 v(3.f, 4.f, 0.f);
  EXPECT_FLOAT_EQ(v.length_sq(), 25.f);
}

TEST(Vec3Test, Normalized) {
  Vec3 v(3.f, 4.f, 0.f);
  Vec3 n = v.normalized();
  EXPECT_NEAR(n.length(), 1.f, 1e-5f);
  EXPECT_NEAR(n.x, 0.6f, 1e-5f);
  EXPECT_NEAR(n.y, 0.8f, 1e-5f);
}

TEST(Vec3Test, NormalizedZeroVector) {
  Vec3 v(0.f, 0.f, 0.f);
  Vec3 n = v.normalized();
  EXPECT_FLOAT_EQ(n.x, 0.f);
  EXPECT_FLOAT_EQ(n.y, 0.f);
  EXPECT_FLOAT_EQ(n.z, 0.f);
}

// ===== Quat Tests =====

TEST(QuatTest, DefaultConstruction) {
  Quat q;
  EXPECT_FLOAT_EQ(q.x, 0.f);
  EXPECT_FLOAT_EQ(q.y, 0.f);
  EXPECT_FLOAT_EQ(q.z, 0.f);
  EXPECT_FLOAT_EQ(q.w, 1.f);
}

TEST(QuatTest, ParameterizedConstruction) {
  Quat q(1.f, 2.f, 3.f, 4.f);
  EXPECT_FLOAT_EQ(q.x, 1.f);
  EXPECT_FLOAT_EQ(q.y, 2.f);
  EXPECT_FLOAT_EQ(q.z, 3.f);
  EXPECT_FLOAT_EQ(q.w, 4.f);
}

TEST(QuatTest, Normalized) {
  Quat q(1.f, 0.f, 0.f, 0.f);
  Quat n = q.normalized();
  float len = std::sqrt(n.x * n.x + n.y * n.y + n.z * n.z + n.w * n.w);
  EXPECT_NEAR(len, 1.f, 1e-5f);
}

TEST(QuatTest, SlerpIdentity) {
  Quat a(0.f, 0.f, 0.f, 1.f);
  Quat b(0.f, 0.f, 0.f, 1.f);
  Quat result = Quat::slerp(a, b, 0.5f);
  EXPECT_NEAR(result.x, 0.f, 1e-5f);
  EXPECT_NEAR(result.y, 0.f, 1e-5f);
  EXPECT_NEAR(result.z, 0.f, 1e-5f);
  EXPECT_NEAR(result.w, 1.f, 1e-5f);
}

TEST(QuatTest, SlerpHalfway) {
  Quat a(0.f, 0.f, 0.f, 1.f);  // Identity
  Quat b(0.f, 0.f, std::sin(3.14159f / 4.f), std::cos(3.14159f / 4.f));  // 90 degree rotation
  Quat result = Quat::slerp(a, b, 0.5f);
  
  // Should be approximately 45 degree rotation
  float expected_z = std::sin(3.14159f / 8.f);
  float expected_w = std::cos(3.14159f / 8.f);
  EXPECT_NEAR(result.z, expected_z, 0.01f);
  EXPECT_NEAR(result.w, expected_w, 0.01f);
}

TEST(QuatTest, SlerpShortestPath) {
  Quat a(0.f, 0.f, 0.f, 1.f);
  Quat b(0.f, 0.f, 0.f, -1.f);  // Same rotation, opposite quaternion
  Quat result = Quat::slerp(a, b, 0.5f);
  // Should take shortest path (not go through -w)
  EXPECT_NEAR(result.w, 1.f, 0.01f);
}

// ===== Interpolator Tests =====

TEST(InterpolatorTest, InitialState) {
  Interpolator interp;
  EXPECT_FALSE(interp.HasStates());
  EXPECT_EQ(interp.GetEntityCount(), 0u);
}

TEST(InterpolatorTest, SaveState) {
  Interpolator interp;
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(1.f, 2.f, 3.f));
  interp.SaveRotation(0, Quat(0.f, 0.f, 0.f, 1.f));
  
  EXPECT_TRUE(interp.HasStates());
  EXPECT_EQ(interp.GetEntityCount(), 1u);
}

TEST(InterpolatorTest, InterpolateSingleFrame) {
  Interpolator interp;
  
  // Save first frame
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.f, 0.f, 0.f));
  interp.SaveRotation(0, Quat(0.f, 0.f, 0.f, 1.f));
  
  // No previous frame, should return current
  auto state = interp.GetInterpolatedState(0, 0.0f, 0.1f);
  EXPECT_FLOAT_EQ(state.position.x, 0.f);
  EXPECT_FLOAT_EQ(state.position.y, 0.f);
  EXPECT_FLOAT_EQ(state.position.z, 0.f);
}

TEST(InterpolatorTest, InterpolateBetweenFrames) {
  Interpolator interp;
  float logic_dt = 0.1f;  // 10 Hz
  
  // Save first frame at t=0
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.f, 0.f, 0.f));
  interp.SaveRotation(0, Quat(0.f, 0.f, 0.f, 1.f));
  
  // Save second frame at t=0.1
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(10.f, 0.f, 0.f));
  interp.SaveRotation(0, Quat(0.f, 0.f, 0.f, 1.f));
  
  // Get interpolated state at t=0.1 (current frame time)
  // Note: The interpolator uses render_time - current_timestamp_ as elapsed
  // So at current_timestamp_, elapsed=0, t=0, which returns previous frame
  // To get current frame, render_time must be > current_timestamp_
  auto state = interp.GetInterpolatedState(0, 0.2f, logic_dt);
  // At t=0.2, elapsed = 0.2 - 0.1 = 0.1, t = 0.1/0.1 = 1.0
  // So we get current frame (position = 10)
  EXPECT_NEAR(state.position.x, 10.f, 0.01f);
  EXPECT_NEAR(state.position.y, 0.f, 0.01f);
  EXPECT_FLOAT_EQ(state.timestamp, 0.2f);
}

TEST(InterpolatorTest, InterpolateAtFrameBoundary) {
  Interpolator interp;
  float logic_dt = 0.1f;
  
  // Save first frame at t=0
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.f, 0.f, 0.f));
  
  // Save second frame at t=0.1
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(10.f, 0.f, 0.f));
  
  // At render_time = current_timestamp_, elapsed=0, t=0, returns previous frame
  auto state = interp.GetInterpolatedState(0, 0.1f, logic_dt);
  EXPECT_NEAR(state.position.x, 0.f, 0.01f);
}

TEST(InterpolatorTest, InterpolateBeforeFrame) {
  Interpolator interp;
  float logic_dt = 0.1f;
  
  // Save first frame at t=0
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.f, 0.f, 0.f));
  
  // Save second frame at t=0.1
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(10.f, 0.f, 0.f));
  
  // Interpolate at t=-0.1 (before first frame)
  auto state = interp.GetInterpolatedState(0, -0.1f, logic_dt);
  EXPECT_NEAR(state.position.x, 0.f, 0.01f);
}

TEST(InterpolatorTest, MultipleEntities) {
  Interpolator interp;
  float logic_dt = 0.1f;
  
  // Save first frame
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.f, 0.f, 0.f));
  interp.SavePosition(1, Vec3(100.f, 0.f, 0.f));
  
  // Save second frame
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(10.f, 0.f, 0.f));
  interp.SavePosition(1, Vec3(110.f, 0.f, 0.f));
  
  // Interpolate both entities at t=0.2 (after second frame)
  auto state0 = interp.GetInterpolatedState(0, 0.2f, logic_dt);
  auto state1 = interp.GetInterpolatedState(1, 0.2f, logic_dt);
  
  EXPECT_NEAR(state0.position.x, 10.f, 0.01f);
  EXPECT_NEAR(state1.position.x, 110.f, 0.01f);
}

TEST(InterpolatorTest, EntityNotFound) {
  Interpolator interp;
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(1.f, 2.f, 3.f));
  
  // Request non-existent entity
  auto state = interp.GetInterpolatedState(99, 0.0f, 0.1f);
  EXPECT_FLOAT_EQ(state.position.x, 0.f);
  EXPECT_FLOAT_EQ(state.position.y, 0.f);
  EXPECT_FLOAT_EQ(state.position.z, 0.f);
}

// ===== Protocol IO Tests =====

TEST(ProtocolIOTest, PackUnpackSessionStart) {
  uint8_t buf[64];
  uint32_t seed = 12345;
  uint16_t left = 2;
  uint16_t right = 3;
  
  size_t packed = PackSessionStart(seed, left, right, buf, sizeof(buf));
  EXPECT_GT(packed, 0u);
  
  uint32_t unpacked_seed;
  uint16_t unpacked_left, unpacked_right;
  size_t unpacked = UnpackSessionStart(buf, packed, &unpacked_seed, &unpacked_left, &unpacked_right);
  EXPECT_EQ(unpacked, packed);
  EXPECT_EQ(unpacked_seed, seed);
  EXPECT_EQ(unpacked_left, left);
  EXPECT_EQ(unpacked_right, right);
}

TEST(ProtocolIOTest, PackUnpackSlotAssignment) {
  uint8_t buf[64];
  uint16_t slots[] = {0, 1, 2};
  uint16_t num_slots = 3;
  
  size_t packed = PackSlotAssignment(slots, num_slots, buf, sizeof(buf));
  EXPECT_GT(packed, 0u);
  
  std::vector<uint16_t> unpacked_slots;
  size_t unpacked = UnpackSlotAssignment(buf, packed, &unpacked_slots);
  EXPECT_EQ(unpacked, packed);
  EXPECT_EQ(unpacked_slots.size(), num_slots);
  for (int i = 0; i < num_slots; ++i) {
    EXPECT_EQ(unpacked_slots[i], slots[i]);
  }
}

TEST(ProtocolIOTest, PackUnpackAuthoritativeFrame) {
  uint8_t buf[256];
  frame_id_t frame_id = 42;
  std::vector<SlotInput> inputs = {{1.f, 2.f, 0x01}, {3.f, 4.f, 0x02}};
  uint16_t num_slots = static_cast<uint16_t>(inputs.size());
  
  size_t packed = PackAuthoritativeFrame(frame_id, inputs.data(), num_slots, buf, sizeof(buf));
  EXPECT_GT(packed, 0u);
  
  frame_id_t unpacked_frame_id;
  std::vector<SlotInput> unpacked_inputs;
  size_t unpacked = UnpackAuthoritativeFrame(buf, packed, &unpacked_frame_id, &unpacked_inputs);
  EXPECT_EQ(unpacked, packed);
  EXPECT_EQ(unpacked_frame_id, frame_id);
  EXPECT_EQ(unpacked_inputs.size(), num_slots);
  for (size_t i = 0; i < num_slots; ++i) {
    EXPECT_EQ(unpacked_inputs[i], inputs[i]);
  }
}

TEST(ProtocolIOTest, PackUnpackClientFrameInput) {
  uint8_t buf[256];
  frame_id_t frame_id = 100;
  std::vector<uint16_t> slot_indices = {0, 1};
  std::vector<SlotInput> inputs = {{1.f, 2.f, 0x01}, {3.f, 4.f, 0x02}};
  
  size_t packed = PackClientFrameInput(frame_id, slot_indices.data(), inputs.data(),
                                       static_cast<uint16_t>(slot_indices.size()),
                                       buf, sizeof(buf));
  EXPECT_GT(packed, 0u);
  
  frame_id_t unpacked_frame_id;
  std::vector<std::pair<uint16_t, SlotInput>> unpacked_entries;
  size_t unpacked = UnpackClientFrameInput(buf, packed, &unpacked_frame_id, &unpacked_entries);
  EXPECT_EQ(unpacked, packed);
  EXPECT_EQ(unpacked_frame_id, frame_id);
  EXPECT_EQ(unpacked_entries.size(), slot_indices.size());
  for (size_t i = 0; i < slot_indices.size(); ++i) {
    EXPECT_EQ(unpacked_entries[i].first, slot_indices[i]);
    EXPECT_EQ(unpacked_entries[i].second, inputs[i]);
  }
}

TEST(ProtocolIOTest, PackReady) {
  uint8_t buf[16];
  size_t packed = PackReady(buf, sizeof(buf));
  EXPECT_EQ(packed, 1u);
  EXPECT_EQ(buf[0], static_cast<uint8_t>(MessageType::Ready));
}

TEST(ProtocolIOTest, PackUnpackStateHash) {
  uint8_t buf[64];
  frame_id_t frame_id = 99;
  state_hash_t hash = 0xDEADBEEFCAFEBABEULL;
  
  size_t packed = PackStateHash(frame_id, hash, buf, sizeof(buf));
  EXPECT_GT(packed, 0u);
  
  frame_id_t unpacked_frame_id;
  state_hash_t unpacked_hash;
  size_t unpacked = UnpackStateHash(buf, packed, &unpacked_frame_id, &unpacked_hash);
  EXPECT_EQ(unpacked, packed);
  EXPECT_EQ(unpacked_frame_id, frame_id);
  EXPECT_EQ(unpacked_hash, hash);
}

TEST(ProtocolIOTest, PackUnpackHeartbeat) {
  uint8_t buf[64];
  frame_id_t frame_id = 50;
  uint32_t timestamp = 12345678;
  
  size_t packed = PackHeartbeat(frame_id, timestamp, buf, sizeof(buf));
  EXPECT_GT(packed, 0u);
  
  heartbeat_t unpacked;
  size_t unpacked_size = UnpackHeartbeat(buf, packed, &unpacked);
  EXPECT_EQ(unpacked_size, packed);
  EXPECT_EQ(unpacked.frame_id, frame_id);
  EXPECT_EQ(unpacked.timestamp_ms, timestamp);
}

TEST(ProtocolIOTest, PackUnpackVersionNegotiate) {
  uint8_t buf[64];
  uint16_t version = 2;
  uint16_t min_version = 1;
  
  size_t packed = PackVersionNegotiate(version, min_version, buf, sizeof(buf));
  EXPECT_GT(packed, 0u);
  
  version_negotiate_t unpacked;
  size_t unpacked_size = UnpackVersionNegotiate(buf, packed, &unpacked);
  EXPECT_EQ(unpacked_size, packed);
  EXPECT_EQ(unpacked.version, version);
  EXPECT_EQ(unpacked.min_version, min_version);
}

// ===== DeltaSlotInput Additional Tests =====

TEST(DeltaSlotInputTest, ConstexprCompute) {
  // Note: memcpy is not constexpr, so we can't test constexpr Compute directly
  // But we can test the runtime behavior
  SlotInput current{1.f, 2.f, 0x03};
  SlotInput previous{1.f, 3.f, 0x01};
  DeltaSlotInput delta = DeltaSlotInput::Compute(current, previous);
  
  // dir_x unchanged, dir_y changed, buttons changed
  EXPECT_EQ(delta.flags, 0x06);
  EXPECT_FLOAT_EQ(delta.dir_x, 1.f);
  EXPECT_FLOAT_EQ(delta.dir_y, 2.f);
  EXPECT_EQ(delta.buttons, 0x03);
}

TEST(DeltaSlotInputTest, PackedSizeTable) {
  // Test all 8 combinations
  DeltaSlotInput d;
  
  d.flags = 0x00; EXPECT_EQ(d.packed_size(), 1u);
  d.flags = 0x01; EXPECT_EQ(d.packed_size(), 5u);
  d.flags = 0x02; EXPECT_EQ(d.packed_size(), 5u);
  d.flags = 0x03; EXPECT_EQ(d.packed_size(), 9u);
  d.flags = 0x04; EXPECT_EQ(d.packed_size(), 3u);
  d.flags = 0x05; EXPECT_EQ(d.packed_size(), 7u);
  d.flags = 0x06; EXPECT_EQ(d.packed_size(), 7u);
  d.flags = 0x07; EXPECT_EQ(d.packed_size(), 11u);
}

TEST(DeltaSlotInputTest, BytesSaved) {
  DeltaSlotInput d;
  d.flags = 0x00;  // No changes
  EXPECT_EQ(d.bytes_saved(), SLOT_INPUT_BYTES - 1);
  
  d.flags = 0x07;  // All changes
  EXPECT_EQ(d.bytes_saved(), SLOT_INPUT_BYTES - 11);
}
