// Copyright 2026 Google LLC & Contributors
#include "frame_sync/frame_simulation.hpp"
#include "frame_sync/state_hash.hpp"
#include <gtest/gtest.h>
#include <array>
#include <cstring>

namespace {
struct Engine {
  std::array<int64_t, 3> state{};  // left position, right position, frame count
  frame_sync::EngineCallbacks Callbacks() {
    frame_sync::EngineCallbacks cb;
    cb.save_state = [&] {
      frame_sync::StateBlob bytes(sizeof(state));
      std::memcpy(bytes.data(), state.data(), bytes.size());
      return bytes;
    };
    cb.restore_state = [&](const auto& bytes) { std::memcpy(state.data(), bytes.data(), sizeof(state)); };
    cb.step_frame = [&](std::span<const frame_sync::SlotInput> inputs) {
      EXPECT_EQ(inputs.size(), 2u);
      state[0] += static_cast<int>(inputs[0].dir_x);
      state[1] += static_cast<int>(inputs[1].dir_x);
      ++state[2];
    };
    cb.compute_hash = [&] { return frame_sync::ComputeStateHash(state.data(), sizeof(state)); };
    return cb;
  }
};
const frame_sync::SlotInput kLeft{1, 0, 0}, kRight{-1, 0, 0};
const std::array<uint16_t, 1> kOwnSlot{0};
}

TEST(FrameSimulationTest, WholeFramePreservesIndependentInputsAndFrameZero) {
  Engine engine;
  frame_sync::FrameSimulation simulation(engine.Callbacks(), 2);
  ASSERT_TRUE(simulation.QueueAuthority(0, {kLeft, kRight}));
  auto tick = simulation.Tick(kLeft, kOwnSlot, 0);
  ASSERT_EQ(tick.confirmed.size(), 1u);
  EXPECT_EQ(engine.state, (std::array<int64_t, 3>{1, -1, 1}));
  EXPECT_EQ(simulation.confirmed_count(), 1u);
}

TEST(FrameSimulationTest, AuthorityUnblocksPredictionAtCap) {
  Engine engine;
  frame_sync::FrameSimulation simulation(engine.Callbacks(), 2);
  for (int i = 0; i < 3; ++i) EXPECT_TRUE(simulation.Tick(kLeft, kOwnSlot).predicted);
  EXPECT_FALSE(simulation.Tick(kLeft, kOwnSlot).predicted);
  ASSERT_TRUE(simulation.QueueAuthority(0, {kLeft, kRight}));
  auto tick = simulation.Tick(kLeft, kOwnSlot);
  EXPECT_TRUE(tick.rolled_back);
  EXPECT_TRUE(tick.predicted);
  EXPECT_EQ(simulation.confirmed_count(), 1u);
  EXPECT_EQ(engine.state[2], 4);
}

TEST(FrameSimulationTest, SuccessiveCorrectionsRefreshLaterSnapshots) {
  Engine engine;
  frame_sync::FrameSimulation simulation(engine.Callbacks(), 2);
  for (int i = 0; i < 3; ++i) simulation.Tick(kLeft, kOwnSlot);
  for (uint32_t frame = 0; frame < 3; ++frame) {
    ASSERT_TRUE(simulation.QueueAuthority(frame, {kLeft, kRight}));
    simulation.Tick(kLeft, kOwnSlot, 0);
  }
  EXPECT_EQ(engine.state, (std::array<int64_t, 3>{3, -3, 3}));
  EXPECT_EQ(simulation.history_size(), 0u);
}

TEST(FrameSimulationTest, OutOfOrderDuplicatesAndThousandFrameRun) {
  Engine engine;
  frame_sync::FrameSimulation simulation(engine.Callbacks(), 2);
  for (uint32_t frame = 0; frame < 1000; frame += 2) {
    ASSERT_TRUE(simulation.QueueAuthority(frame + 1, {kLeft, kRight}));
    ASSERT_TRUE(simulation.QueueAuthority(frame, {kLeft, kRight}));
    ASSERT_TRUE(simulation.QueueAuthority(frame, {kLeft, kRight}));
    auto tick = simulation.Tick(kLeft, kOwnSlot, 0);
    ASSERT_EQ(tick.confirmed.size(), 2u);
    EXPECT_EQ(simulation.VerifyHash(frame + 1, tick.confirmed.back().hash), true);
    EXPECT_EQ(simulation.VerifyHash(frame + 1, tick.confirmed.back().hash ^ 1), false);
  }
  EXPECT_EQ(engine.state, (std::array<int64_t, 3>{1000, -1000, 1000}));
  EXPECT_EQ(simulation.history_size(), 0u);
  EXPECT_FALSE(simulation.QueueAuthority(99999, {kLeft, kRight}));
  EXPECT_FALSE(simulation.QueueAuthority(1000, {kLeft}));
}

TEST(FrameSimulationTest, HashMatchesPythonSha256LittleEndianPrefix) {
  EXPECT_EQ(frame_sync::ComputeStateHash("", 0), 0x141cfc9842c4b0e3ULL);
  EXPECT_EQ(frame_sync::ComputeStateHash("abc", 3), 0xeacf018fbf1678baULL);
}

TEST(FrameSimulationTest, MissingAuthorityStopsEvenWithExpandedPredictionWindow) {
  Engine engine;
  frame_sync::FrameSimulation simulation(engine.Callbacks(), 2);
  for (int i = 0; i < frame_sync::MAX_FRAMES_WITHOUT_PACKET - 1; ++i)
    EXPECT_TRUE(simulation.Tick(kLeft, kOwnSlot, 8).predicted);
  EXPECT_FALSE(simulation.Tick(kLeft, kOwnSlot, 8).predicted);
  ASSERT_TRUE(simulation.QueueAuthority(0, {kLeft, kRight}));
  EXPECT_TRUE(simulation.Tick(kLeft, kOwnSlot, 8).predicted);
}
