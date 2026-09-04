// Copyright 2026 Google LLC & Contributors
// Unit tests for ReplaySystem (ms-16.7)

#include "frame_sync/replay_system.hpp"

#include <gtest/gtest.h>

namespace frame_sync {
namespace {

// Test basic recording
TEST(ReplaySystemTest, BasicRecording) {
  ReplayRecorder recorder;
  
  recorder.StartRecording(12345, "test_scenario", 2);
  EXPECT_TRUE(recorder.IsRecording());
  
  // Record some frames
  for (uint32_t i = 0; i < 10; ++i) {
    std::vector<SlotInput> inputs(2);
    inputs[0].dir_x = static_cast<float>(i);
    inputs[1].dir_y = static_cast<float>(i * 2);
    recorder.RecordFrame(i, i * 1000, inputs);
  }
  
  recorder.StopRecording();
  EXPECT_FALSE(recorder.IsRecording());
  EXPECT_EQ(recorder.GetFrameCount(), 10u);
  
  auto metadata = recorder.GetMetadata();
  EXPECT_EQ(metadata.seed, 12345u);
  EXPECT_EQ(metadata.scenario, "test_scenario");
  EXPECT_EQ(metadata.total_frames, 10u);
  EXPECT_EQ(metadata.num_slots, 2u);
  EXPECT_EQ(metadata.final_state_hash, 9000u);
}

// Test serialization and deserialization
TEST(ReplaySystemTest, SerializationRoundtrip) {
  ReplayRecorder recorder;
  
  recorder.StartRecording(54321, "roundtrip_test", 3);
  
  for (uint32_t i = 0; i < 20; ++i) {
    std::vector<SlotInput> inputs(3);
    inputs[0].dir_x = static_cast<float>(i) * 0.1f;
    inputs[0].dir_y = static_cast<float>(i) * 0.2f;
    inputs[0].buttons = static_cast<uint16_t>(i % 4);
    inputs[1].dir_x = static_cast<float>(i) * 0.3f;
    inputs[2].dir_y = static_cast<float>(i) * 0.4f;
    recorder.RecordFrame(i, i * 500, inputs);
  }
  
  recorder.StopRecording();
  std::string serialized = recorder.Serialize();
  EXPECT_FALSE(serialized.empty());
  
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(serialized));
  EXPECT_TRUE(player.IsLoaded());
  
  auto metadata = player.GetMetadata();
  EXPECT_EQ(metadata.seed, 54321u);
  EXPECT_EQ(metadata.scenario, "roundtrip_test");
  EXPECT_EQ(metadata.total_frames, 20u);
  EXPECT_EQ(metadata.num_slots, 3u);
}

// Test playback
TEST(ReplaySystemTest, Playback) {
  ReplayRecorder recorder;
  
  recorder.StartRecording(111, "playback_test", 1);
  
  for (uint32_t i = 0; i < 5; ++i) {
    std::vector<SlotInput> inputs(1);
    inputs[0].dir_x = static_cast<float>(i);
    recorder.RecordFrame(i, i * 100, inputs);
  }
  
  recorder.StopRecording();
  
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(recorder.Serialize()));
  
  player.Play();
  EXPECT_TRUE(player.IsPlaying());
  
  // Check first frame
  auto frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 0u);
  EXPECT_EQ(frame->state_hash, 0u);
  EXPECT_FLOAT_EQ(frame->inputs[0].dir_x, 0.0f);
  
  // Advance through frames
  EXPECT_TRUE(player.Advance());
  frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 1u);
  EXPECT_EQ(frame->state_hash, 100u);
  
  EXPECT_TRUE(player.Advance());
  EXPECT_TRUE(player.Advance());
  EXPECT_TRUE(player.Advance());
  
  // Last frame
  frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 4u);
  
  // No more frames
  EXPECT_FALSE(player.Advance());
  EXPECT_FALSE(player.IsPlaying());
  EXPECT_TRUE(player.IsAtEnd());
}

// Test seeking
TEST(ReplaySystemTest, Seeking) {
  ReplayRecorder recorder;
  
  recorder.StartRecording(222, "seek_test", 1);
  
  for (uint32_t i = 0; i < 10; ++i) {
    std::vector<SlotInput> inputs(1);
    inputs[0].dir_x = static_cast<float>(i);
    recorder.RecordFrame(i, i * 100, inputs);
  }
  
  recorder.StopRecording();
  
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(recorder.Serialize()));
  
  // Seek to middle
  EXPECT_TRUE(player.SeekToFrame(5));
  auto frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 5u);
  EXPECT_FLOAT_EQ(frame->inputs[0].dir_x, 5.0f);
  
  // Seek to beginning
  EXPECT_TRUE(player.SeekToFrame(0));
  frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 0u);
  
  // Seek to end
  EXPECT_TRUE(player.SeekToFrame(9));
  EXPECT_TRUE(player.IsAtEnd());
  
  // Seek to invalid frame
  EXPECT_FALSE(player.SeekToFrame(100));
}

// Test frame at index
TEST(ReplaySystemTest, FrameAtIndex) {
  ReplayRecorder recorder;
  
  recorder.StartRecording(333, "index_test", 1);
  
  for (uint32_t i = 0; i < 5; ++i) {
    std::vector<SlotInput> inputs(1);
    inputs[0].dir_x = static_cast<float>(i);
    recorder.RecordFrame(i, i * 100, inputs);
  }
  
  recorder.StopRecording();
  
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(recorder.Serialize()));
  
  auto frame = player.GetFrameAt(0);
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 0u);
  
  frame = player.GetFrameAt(4);
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 4u);
  
  frame = player.GetFrameAt(10);
  EXPECT_FALSE(frame.has_value());
}

// Test pause and resume
TEST(ReplaySystemTest, PauseResume) {
  ReplayRecorder recorder;
  
  recorder.StartRecording(444, "pause_test", 1);
  
  for (uint32_t i = 0; i < 5; ++i) {
    std::vector<SlotInput> inputs(1);
    recorder.RecordFrame(i, i * 100, inputs);
  }
  
  recorder.StopRecording();
  
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(recorder.Serialize()));
  
  player.Play();
  EXPECT_TRUE(player.IsPlaying());
  
  player.Advance();
  player.Advance();
  
  player.Pause();
  EXPECT_FALSE(player.IsPlaying());
  
  auto frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 2u);
  
  // Resume
  player.Play();
  EXPECT_TRUE(player.IsPlaying());
  player.Advance();
  
  frame = player.GetCurrentFrame();
  EXPECT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 3u);
}

// Test reset
TEST(ReplaySystemTest, Reset) {
  ReplayRecorder recorder;
  
  recorder.StartRecording(555, "reset_test", 1);
  
  for (uint32_t i = 0; i < 5; ++i) {
    std::vector<SlotInput> inputs(1);
    recorder.RecordFrame(i, i * 100, inputs);
  }
  
  recorder.StopRecording();
  
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(recorder.Serialize()));
  
  player.Play();
  player.Advance();
  player.Advance();
  
  player.Reset();
  EXPECT_FALSE(player.IsPlaying());
  EXPECT_EQ(player.GetCurrentFrameIndex(), 0u);
}

// Test empty replay
TEST(ReplaySystemTest, EmptyReplay) {
  ReplayRecorder recorder;
  recorder.StartRecording(666, "empty_test", 1);
  recorder.StopRecording();
  
  std::string serialized = recorder.Serialize();
  EXPECT_FALSE(serialized.empty());
  
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(serialized));
  EXPECT_EQ(player.GetTotalFrames(), 0u);
  
  player.Play();
  EXPECT_FALSE(player.IsPlaying());
}

// Test metadata
TEST(ReplaySystemTest, Metadata) {
  ReplayRecorder recorder;
  
  recorder.StartRecording(777, "metadata_test", 4);
  
  for (uint32_t i = 0; i < 100; ++i) {
    std::vector<SlotInput> inputs(4);
    recorder.RecordFrame(i, i * 1000, inputs);
  }
  
  recorder.StopRecording();
  
  auto metadata = recorder.GetMetadata();
  EXPECT_EQ(metadata.seed, 777u);
  EXPECT_EQ(metadata.scenario, "metadata_test");
  EXPECT_EQ(metadata.total_frames, 100u);
  EXPECT_EQ(metadata.num_slots, 4u);
  EXPECT_EQ(metadata.final_state_hash, 99000u);
}

}  // namespace
}  // namespace frame_sync
