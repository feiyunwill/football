// Copyright 2026 Google LLC & Contributors
// Unit tests for frame_sync::ClientState (prediction/rollback ring buffer).

#include "frame_sync/client_state.hpp"
#include "frame_sync/protocol.hpp"

#include <gtest/gtest.h>
#include <vector>
#include <cstdint>

namespace fs = frame_sync;

// ===== Helper: fake engine state =====

// A trivial "engine" that tracks which inputs were applied.
struct FakeEngine {
  std::vector<fs::SlotInput> applied_inputs;
  int step_count = 0;

  fs::StateBlob save() {
    // Serialize step_count as state blob.
    fs::StateBlob blob(sizeof(int));
    std::memcpy(blob.data(), &step_count, sizeof(int));
    return blob;
  }

  void restore(const fs::StateBlob& blob) {
    ASSERT_EQ(blob.size(), sizeof(int));
    std::memcpy(&step_count, blob.data(), sizeof(int));
  }

  void step(const fs::SlotInput& input) {
    applied_inputs.push_back(input);
    ++step_count;
  }
};

// ===== Tests: Basic snapshot operations =====

class ClientStateTest : public ::testing::Test {
 protected:
  void SetUp() override {
    cs_ = fs::ClientState(8);  // buffer of 8 frames
  }

  fs::ClientState cs_;
  FakeEngine engine_;
};

TEST_F(ClientStateTest, SaveAndRetrieve) {
  fs::SlotInput input;
  input.dir_x = 1.0f;
  input.buttons = 0x01;

  cs_.save_snapshot(0, input, [&]() { return engine_.save(); });
  engine_.step(input);

  const auto* snap = cs_.get_snapshot(0);
  ASSERT_NE(snap, nullptr);
  EXPECT_EQ(snap->frame_id, 0u);
  EXPECT_EQ(snap->predicted_input.dir_x, 1.0f);
  EXPECT_EQ(snap->predicted_input.buttons, 0x01u);
}

TEST_F(ClientStateTest, MultipleSnapshots) {
  for (int i = 0; i < 5; ++i) {
    fs::SlotInput input;
    input.dir_x = static_cast<float>(i);
    cs_.save_snapshot(i, input, [&]() { return engine_.save(); });
    engine_.step(input);
  }

  EXPECT_EQ(cs_.buffer_size(), 5);

  for (int i = 0; i < 5; ++i) {
    const auto* snap = cs_.get_snapshot(i);
    ASSERT_NE(snap, nullptr) << "frame " << i;
    EXPECT_EQ(snap->frame_id, static_cast<fs::frame_id_t>(i));
  }
}

TEST_F(ClientStateTest, GetSnapshotNotFound) {
  const auto* snap = cs_.get_snapshot(999);
  EXPECT_EQ(snap, nullptr);
}

// ===== Tests: Eviction =====

TEST_F(ClientStateTest, Eviction) {
  // Buffer size is 8, so after 12 saves, only 8 should remain.
  for (int i = 0; i < 12; ++i) {
    fs::SlotInput input;
    cs_.save_snapshot(i, input, [&]() { return engine_.save(); });
  }

  EXPECT_EQ(cs_.buffer_size(), 8);
  EXPECT_GE(cs_.evict_count(), 4);

  // Oldest remaining should be frame 4
  EXPECT_EQ(cs_.get_snapshot(3), nullptr);
  EXPECT_NE(cs_.get_snapshot(4), nullptr);
}

// ===== Tests: Rollback =====

TEST_F(ClientStateTest, RollbackRestoresState) {
  // Save snapshot at frame 0, step to frame 1,2,3
  fs::SlotInput input;
  cs_.save_snapshot(0, input, [&]() { return engine_.save(); });
  engine_.step(input);  // step 1

  cs_.save_snapshot(1, input, [&]() { return engine_.save(); });
  engine_.step(input);  // step 2

  cs_.save_snapshot(2, input, [&]() { return engine_.save(); });
  engine_.step(input);  // step 3

  EXPECT_EQ(engine_.step_count, 3);

  // Rollback to frame 1 with authoritative input
  fs::SlotInput auth_input;
  auth_input.dir_x = 99.0f;

  bool ok = cs_.rollback_to(1, auth_input,
                             [&](const fs::StateBlob& b) { engine_.restore(b); },
                             [&](const fs::SlotInput& inp) { engine_.step(inp); });

  EXPECT_TRUE(ok);
  EXPECT_EQ(engine_.step_count, 2);  // restored to frame 1 (step_count=1), then stepped once
  EXPECT_EQ(cs_.rollback_count(), 1);

  // The authoritative input should have been applied
  ASSERT_FALSE(engine_.applied_inputs.empty());
  EXPECT_EQ(engine_.applied_inputs.back().dir_x, 99.0f);
}

TEST_F(ClientStateTest, RollbackNotFound) {
  fs::SlotInput input;
  cs_.save_snapshot(0, input, [&]() { return engine_.save(); });

  bool ok = cs_.rollback_to(5, input,
                             [&](const fs::StateBlob& b) { engine_.restore(b); },
                             [&](const fs::SlotInput& inp) { engine_.step(inp); });

  EXPECT_FALSE(ok);
}

TEST_F(ClientStateTest, RestoreSnapshotWithoutStep) {
  fs::SlotInput input;
  cs_.save_snapshot(0, input, [&]() { return engine_.save(); });
  engine_.step(input);  // step 1
  cs_.save_snapshot(1, input, [&]() { return engine_.save(); });
  engine_.step(input);  // step 2

  bool ok = cs_.restore_snapshot(0,
                                 [&](const fs::StateBlob& b) { engine_.restore(b); });
  EXPECT_TRUE(ok);
  EXPECT_EQ(engine_.step_count, 0);  // restored but NOT stepped
}

// ===== Tests: State hash verification =====

TEST_F(ClientStateTest, StateHashMatch) {
  cs_.record_server_hash(10, 0xDEADBEEF);
  EXPECT_EQ(cs_.check_hash(10, 0xDEADBEEF), fs::ClientState::HashCheck::kMatch);
}

TEST_F(ClientStateTest, StateHashMismatch) {
  cs_.record_server_hash(10, 0xDEADBEEF);
  EXPECT_EQ(cs_.check_hash(10, 0xCAFEBABE), fs::ClientState::HashCheck::kMismatch);
}

TEST_F(ClientStateTest, StateHashUnknown) {
  cs_.record_server_hash(10, 0xDEADBEEF);
  EXPECT_EQ(cs_.check_hash(99, 0xDEADBEEF), fs::ClientState::HashCheck::kUnknown);
}

// ===== Tests: Full prediction/rollback cycle =====

TEST_F(ClientStateTest, FullPredictionRollbackCycle) {
  // Simulate: predict frames 0-3, then receive authoritative frame 2
  // with different input → rollback to frame 2 and re-simulate.

  // Frame 0: save, step with predicted input A
  fs::SlotInput input_a;
  input_a.dir_x = 1.0f;
  cs_.save_snapshot(0, input_a, [&]() { return engine_.save(); });
  engine_.step(input_a);

  // Frame 1: save, step with predicted input A
  cs_.save_snapshot(1, input_a, [&]() { return engine_.save(); });
  engine_.step(input_a);

  // Frame 2: save, step with predicted input A
  cs_.save_snapshot(2, input_a, [&]() { return engine_.save(); });
  engine_.step(input_a);

  // Frame 3: save, step with predicted input A
  cs_.save_snapshot(3, input_a, [&]() { return engine_.save(); });
  engine_.step(input_a);

  EXPECT_EQ(engine_.step_count, 4);

  // Server sends authoritative frame 2 with input B (different from predicted)
  fs::SlotInput input_b;
  input_b.dir_x = -1.0f;

  bool ok = cs_.rollback_to(2, input_b,
                             [&](const fs::StateBlob& b) { engine_.restore(b); },
                             [&](const fs::SlotInput& inp) { engine_.step(inp); });

  EXPECT_TRUE(ok);
  EXPECT_EQ(cs_.rollback_count(), 1);

  // Now we'd re-simulate frames 2 and 3 with authoritative inputs.
  // The engine was restored to frame 2 state, then stepped with input_b.
  // So step_count should be 3 (restored to 2, then stepped once).
  EXPECT_EQ(engine_.step_count, 3);
}

// ===== Tests: Clear =====

TEST_F(ClientStateTest, ClearResetsEverything) {
  for (int i = 0; i < 5; ++i) {
    fs::SlotInput input;
    cs_.save_snapshot(i, input, [&]() { return engine_.save(); });
  }
  cs_.record_server_hash(5, 12345);

  cs_.clear();

  EXPECT_EQ(cs_.buffer_size(), 0);
  EXPECT_EQ(cs_.rollback_count(), 0);
  EXPECT_EQ(cs_.get_snapshot(0), nullptr);
  EXPECT_EQ(cs_.check_hash(5, 12345), fs::ClientState::HashCheck::kUnknown);
}

// ===== Tests: Dynamic frame catching =====

TEST_F(ClientStateTest, CatchupWhenBehind) {
  // Server is at frame 5, client at frame 2 → should catch up 3 frames
  int count = cs_.catchup_count(5, 2);
  EXPECT_EQ(count, 3);  // min(5-2, kMaxCatchupFramesPerTick=3)
}

TEST_F(ClientStateTest, CatchupCappedAtMax) {
  // Server is at frame 10, client at frame 0 → catch up capped at 3
  int count = cs_.catchup_count(10, 0);
  EXPECT_EQ(count, 3);  // kMaxCatchupFramesPerTick
}

TEST_F(ClientStateTest, NoCatchupWhenSynced) {
  // Server and client at same frame → normal processing
  int count = cs_.catchup_count(5, 5);
  EXPECT_EQ(count, 1);  // normal
}

TEST_F(ClientStateTest, WaitWhenAhead) {
  // Client is ahead of server → wait
  int count = cs_.catchup_count(3, 5);
  EXPECT_EQ(count, -1);  // wait
}

TEST_F(ClientStateTest, FramesBehindCalculation) {
  EXPECT_EQ(cs_.frames_behind(10, 7), 3);
  EXPECT_EQ(cs_.frames_behind(5, 5), 0);
  EXPECT_EQ(cs_.frames_behind(3, 7), -4);
}

// ===== Tests: Jitter tracking =====

TEST_F(ClientStateTest, JitterTracking) {
  // Record arrivals at 100ms intervals (steady)
  cs_.record_frame_arrival(1000.0);
  cs_.record_frame_arrival(1100.0);
  cs_.record_frame_arrival(1200.0);
  cs_.record_frame_arrival(1300.0);

  EXPECT_NEAR(cs_.avg_frame_interval_ms(), 100.0, 0.01);
  EXPECT_NEAR(cs_.jitter_ms(), 0.0, 0.01);
  EXPECT_FALSE(cs_.is_jitter_high());
}

TEST_F(ClientStateTest, JitterHigh) {
  // Record arrivals with high jitter
  cs_.record_frame_arrival(1000.0);
  cs_.record_frame_arrival(1050.0);   // 50ms
  cs_.record_frame_arrival(1200.0);   // 150ms
  cs_.record_frame_arrival(1220.0);   // 20ms
  cs_.record_frame_arrival(1400.0);   // 180ms

  EXPECT_GT(cs_.jitter_ms(), fs::kJitterHighThresholdMs);
  EXPECT_TRUE(cs_.is_jitter_high());
}

TEST_F(ClientStateTest, JitterResetsOnClear) {
  cs_.record_frame_arrival(1000.0);
  cs_.record_frame_arrival(1200.0);

  cs_.clear();

  EXPECT_EQ(cs_.avg_frame_interval_ms(), 0.0);
  EXPECT_EQ(cs_.jitter_ms(), 0.0);
}
