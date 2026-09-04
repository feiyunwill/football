// Copyright 2026 Google LLC & Contributors
// Unit tests for AdaptiveJitterBuffer (ms-16.8)

#include "frame_sync/adaptive_jitter_buffer.hpp"

#include <gtest/gtest.h>

namespace frame_sync {
namespace {

// Test default values
TEST(AdaptiveJitterBufferTest, DefaultValues) {
  AdaptiveJitterBuffer buffer;
  
  int frames = buffer.GetRecommendedBufferFrames();
  EXPECT_GE(frames, 1);
  EXPECT_LE(frames, 10);
  
  double ms = buffer.GetRecommendedBufferMs();
  EXPECT_GT(ms, 0.0);
}

// Test jitter-based scaling
TEST(AdaptiveJitterBufferTest, JitterScaling) {
  AdaptiveJitterBuffer buffer;
  
  // Low jitter → small buffer
  buffer.Update(5.0, 30.0);
  int low_jitter = buffer.GetRecommendedBufferFrames();
  
  // High jitter → larger buffer
  buffer.Reset();
  buffer.Update(50.0, 30.0);
  int high_jitter = buffer.GetRecommendedBufferFrames();
  
  EXPECT_GE(high_jitter, low_jitter);
}

// Test RTT adjustment
TEST(AdaptiveJitterBufferTest, RTTAdjustment) {
  AdaptiveJitterBuffer buffer;
  
  // Same jitter, different RTT
  buffer.Update(20.0, 30.0);
  int low_rtt = buffer.GetRecommendedBufferFrames();
  
  buffer.Reset();
  buffer.Update(20.0, 150.0);
  int high_rtt = buffer.GetRecommendedBufferFrames();
  
  EXPECT_GE(high_rtt, low_rtt);
}

// Test frame arrival tracking
TEST(AdaptiveJitterBufferTest, FrameArrival) {
  AdaptiveJitterBuffer buffer;
  
  buffer.Update(10.0, 50.0);
  
  // Simulate regular frame arrivals
  for (uint32_t i = 0; i < 10; ++i) {
    buffer.OnFrameArrived(i);
  }
  
  auto status = buffer.GetStatus();
  EXPECT_EQ(status.gap_count, 0);
  EXPECT_GT(status.avg_inter_arrival_ms, 0.0);
}

// Test gap detection
TEST(AdaptiveJitterBufferTest, GapDetection) {
  AdaptiveJitterBuffer buffer;
  
  buffer.Update(10.0, 50.0);
  
  // Simulate frame arrivals with gaps
  buffer.OnFrameArrived(0);
  buffer.OnFrameArrived(2);  // Gap: missed frame 1
  buffer.OnFrameArrived(5);  // Gap: missed frames 3, 4
  
  auto status = buffer.GetStatus();
  EXPECT_GT(status.gap_count, 0);
}

// Test frame drop decision
TEST(AdaptiveJitterBufferTest, FrameDrop) {
  AdaptiveJitterBuffer buffer;
  
  buffer.Update(10.0, 50.0);
  int buffer_frames = buffer.GetRecommendedBufferFrames();
  
  // Current frame is 100
  uint32_t current_frame = 100;
  
  // Recent frame should not be dropped
  EXPECT_FALSE(buffer.ShouldDropFrame(99, current_frame));
  
  // Very old frame should be dropped
  EXPECT_TRUE(buffer.ShouldDropFrame(1, current_frame));
}

// Test buffer status
TEST(AdaptiveJitterBufferTest, BufferStatus) {
  AdaptiveJitterBuffer buffer;
  
  // Multiple updates to stabilize smoothing
  for (int i = 0; i < 10; ++i) {
    buffer.Update(25.0, 80.0);
  }
  
  auto status = buffer.GetStatus();
  EXPECT_GE(status.recommended_frames, 1);
  EXPECT_LE(status.recommended_frames, 10);
  EXPECT_GT(status.recommended_ms, 0.0);
  EXPECT_NEAR(status.smoothed_jitter_ms, 25.0, 5.0);
  EXPECT_DOUBLE_EQ(status.rtt_ms, 80.0);
}

// Test reset
TEST(AdaptiveJitterBufferTest, Reset) {
  AdaptiveJitterBuffer buffer;
  
  buffer.Update(50.0, 200.0);
  buffer.OnFrameArrived(0);
  buffer.OnFrameArrived(5);
  
  buffer.Reset();
  
  EXPECT_DOUBLE_EQ(buffer.GetSmoothedJitter(), 0.0);
  EXPECT_EQ(buffer.GetGapCount(), 0);
}

// Test smoothing
TEST(AdaptiveJitterBufferTest, Smoothing) {
  AdaptiveJitterBuffer buffer;
  
  // First update sets initial value
  buffer.Update(100.0, 50.0);
  double first = buffer.GetSmoothedJitter();
  
  // Second update should smooth
  buffer.Update(0.0, 50.0);
  double second = buffer.GetSmoothedJitter();
  
  // Smoothed value should be between the two inputs
  EXPECT_GT(second, 0.0);
  EXPECT_LT(second, 100.0);
}

// Test clamping
TEST(AdaptiveJitterBufferTest, Clamping) {
  AdaptiveJitterBuffer buffer;
  
  // Extreme conditions should still be in valid range
  buffer.Update(1000.0, 1000.0);
  int frames = buffer.GetRecommendedBufferFrames();
  EXPECT_GE(frames, 1);
  EXPECT_LE(frames, 10);
}

}  // namespace
}  // namespace frame_sync
