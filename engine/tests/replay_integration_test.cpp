// Copyright 2026 Google LLC & Contributors
// Replay integration test (ms-17.4)
// Verifies ReplayRecorder roundtrip: record → serialize → deserialize → verify

#include "frame_sync/replay_system.hpp"
#include "frame_sync/protocol.hpp"

#include <gtest/gtest.h>
#include <cstdio>
#include <string>
#include <vector>
#include <filesystem>

namespace frame_sync {
namespace {

// Test: Record frames, serialize, load, and verify
TEST(ReplayIntegrationTest, RecordSerializeLoadRoundtrip) {
  ReplayRecorder recorder;
  recorder.StartRecording(42, "academy_empty_goal_close", 2);

  // Record 100 frames with varying inputs
  for (uint32_t i = 0; i < 100; ++i) {
    std::vector<SlotInput> inputs(2);
    inputs[0].dir_x = static_cast<float>(i % 10) / 10.0f;
    inputs[0].buttons = static_cast<uint16_t>(i & 0x0F);
    inputs[1].dir_y = static_cast<float>(i % 5) / 5.0f;
    recorder.RecordFrame(i, static_cast<uint64_t>(i) * 1000, inputs);
  }

  recorder.StopRecording();
  EXPECT_EQ(recorder.GetFrameCount(), 100u);
  EXPECT_FALSE(recorder.IsRecording());

  // Serialize
  std::string data = recorder.Serialize();
  EXPECT_GT(data.size(), 0u);

  // Load into player
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(data));
  EXPECT_TRUE(player.IsLoaded());

  auto meta = player.GetMetadata();
  EXPECT_EQ(meta.seed, 42u);
  EXPECT_EQ(meta.scenario, "academy_empty_goal_close");
  EXPECT_EQ(meta.num_slots, 2u);
  EXPECT_EQ(meta.total_frames, 100u);

  // Verify frame data
  EXPECT_EQ(player.GetTotalFrames(), 100u);

  auto frame0 = player.GetFrameAt(0);
  ASSERT_TRUE(frame0.has_value());
  EXPECT_EQ(frame0->frame_number, 0u);
  EXPECT_EQ(frame0->state_hash, 0u);
  EXPECT_EQ(frame0->inputs.size(), 2u);
  EXPECT_FLOAT_EQ(frame0->inputs[0].dir_x, 0.0f);
  EXPECT_EQ(frame0->inputs[0].buttons, 0);

  auto frame50 = player.GetFrameAt(50);
  ASSERT_TRUE(frame50.has_value());
  EXPECT_EQ(frame50->frame_number, 50u);
  EXPECT_FLOAT_EQ(frame50->inputs[0].dir_x, 0.0f);  // 50 % 10 = 0
  EXPECT_EQ(frame50->inputs[0].buttons, 50 & 0x0F);

  auto frame99 = player.GetFrameAt(99);
  ASSERT_TRUE(frame99.has_value());
  EXPECT_EQ(frame99->frame_number, 99u);
}

// Test: ReplayPlayer playback
TEST(ReplayIntegrationTest, PlaybackControls) {
  ReplayRecorder recorder;
  recorder.StartRecording(123, "test_scenario", 1);

  for (uint32_t i = 0; i < 10; ++i) {
    std::vector<SlotInput> inputs(1);
    inputs[0].dir_x = static_cast<float>(i) / 10.0f;
    recorder.RecordFrame(i, i, inputs);
  }
  recorder.StopRecording();

  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(recorder.Serialize()));

  // Play
  player.Play();
  EXPECT_TRUE(player.IsPlaying());

  auto frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 0u);

  // Advance
  EXPECT_TRUE(player.Advance());
  frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 1u);

  // Seek
  EXPECT_TRUE(player.SeekToFrame(5));
  frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 5u);

  // Advance to end
  for (int i = 0; i < 4; ++i) {
    EXPECT_TRUE(player.Advance());
  }
  EXPECT_TRUE(player.IsAtEnd());
  EXPECT_FALSE(player.Advance());  // Can't go past end

  // Reset
  player.Reset();
  EXPECT_FALSE(player.IsPlaying());
  frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 0u);
}

// Test: File save/load roundtrip
TEST(ReplayIntegrationTest, FileSaveLoad) {
  ReplayRecorder recorder;
  recorder.StartRecording(999, "file_test", 2);

  for (uint32_t i = 0; i < 10; ++i) {
    std::vector<SlotInput> inputs(2);
    inputs[0].dir_x = 0.5f;
    recorder.RecordFrame(i, i * 100, inputs);
  }
  recorder.StopRecording();

  std::string data = recorder.Serialize();
  std::string path = "test_replay_999.bin";

  // Save to file
  FILE* f = fopen(path.c_str(), "wb");
  ASSERT_NE(f, nullptr);
  fwrite(data.data(), 1, data.size(), f);
  fclose(f);

  // Load from file
  FILE* f2 = fopen(path.c_str(), "rb");
  ASSERT_NE(f2, nullptr);
  fseek(f2, 0, SEEK_END);
  long size = ftell(f2);
  fseek(f2, 0, SEEK_SET);
  std::string loaded_data(size, '\0');
  fread(loaded_data.data(), 1, size, f2);
  fclose(f2);

  EXPECT_EQ(loaded_data, data);

  // Verify loaded replay
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(loaded_data));
  EXPECT_EQ(player.GetTotalFrames(), 10u);

  // Cleanup
  std::filesystem::remove(path);
}

// Test: Empty replay
TEST(ReplayIntegrationTest, EmptyReplay) {
  ReplayRecorder recorder;
  recorder.StartRecording(1, "empty", 1);
  recorder.StopRecording();

  std::string data = recorder.Serialize();
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(data));
  EXPECT_EQ(player.GetTotalFrames(), 0u);
  EXPECT_FALSE(player.GetCurrentFrame().has_value());
}

}  // namespace
}  // namespace frame_sync
