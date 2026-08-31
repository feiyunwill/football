// Copyright 2026 Google LLC & Contributors
// Tests for UX optimizer.

#include "frame_sync/ux_optimizer.hpp"
#include <gtest/gtest.h>
#include <thread>
#include <chrono>

using namespace frame_sync;

class UXOptimizerTest : public ::testing::Test {};

TEST_F(UXOptimizerTest, InitialState) {
  UXOptimizer optimizer;
  auto stats = optimizer.GetStats();
  
  EXPECT_DOUBLE_EQ(stats.avg_input_latency_ms, 0.0);
  EXPECT_DOUBLE_EQ(stats.max_input_latency_ms, 0.0);
  EXPECT_DOUBLE_EQ(stats.p95_input_latency_ms, 0.0);
  EXPECT_DOUBLE_EQ(stats.avg_frame_time_ms, 0.0);
  EXPECT_DOUBLE_EQ(stats.frame_time_jitter_ms, 0.0);
  EXPECT_DOUBLE_EQ(stats.fps, 0.0);
  EXPECT_EQ(stats.network_quality, NetworkQuality::kExcellent);  // No data = excellent
  EXPECT_DOUBLE_EQ(stats.smoothed_rtt_ms, 0.0);
  EXPECT_DOUBLE_EQ(stats.packet_loss_rate, 0.0);
  EXPECT_DOUBLE_EQ(stats.prediction_accuracy, 0.0);
  EXPECT_EQ(stats.rollback_count, 0);
  EXPECT_EQ(stats.total_frames, 0);
}

TEST_F(UXOptimizerTest, RecordInputLatency) {
  UXOptimizer optimizer;
  
  // Record some latencies
  optimizer.RecordInputLatency(50.0);
  optimizer.RecordInputLatency(60.0);
  optimizer.RecordInputLatency(70.0);
  
  auto stats = optimizer.GetStats();
  
  EXPECT_DOUBLE_EQ(stats.avg_input_latency_ms, 60.0);
  EXPECT_DOUBLE_EQ(stats.max_input_latency_ms, 70.0);
  EXPECT_EQ(stats.total_frames, 3);
}

TEST_F(UXOptimizerTest, RecordFrameTime) {
  UXOptimizer optimizer;
  
  // Record some frame times (60 FPS = ~16.67ms)
  for (int i = 0; i < 10; ++i) {
    optimizer.RecordFrameTime(16.67);
  }
  
  auto stats = optimizer.GetStats();
  
  EXPECT_NEAR(stats.avg_frame_time_ms, 16.67, 0.01);
  EXPECT_NEAR(stats.fps, 60.0, 1.0);
}

TEST_F(UXOptimizerTest, NetworkQuality) {
  UXOptimizer optimizer;
  
  // Excellent network (low RTT, no loss)
  for (int i = 0; i < 10; ++i) {
    optimizer.RecordInputLatency(30.0);
    optimizer.RecordPacketLoss(0.0);
  }
  
  auto stats = optimizer.GetStats();
  EXPECT_EQ(stats.network_quality, NetworkQuality::kExcellent);
  
  // Reset and test poor network
  optimizer.Reset();
  for (int i = 0; i < 10; ++i) {
    optimizer.RecordInputLatency(180.0);
    optimizer.RecordPacketLoss(0.04);
  }
  
  stats = optimizer.GetStats();
  EXPECT_EQ(stats.network_quality, NetworkQuality::kPoor);
}

TEST_F(UXOptimizerTest, PredictionAccuracy) {
  UXOptimizer optimizer;
  
  // Record predictions (80% correct)
  for (int i = 0; i < 10; ++i) {
    optimizer.RecordPrediction(i < 8);
  }
  
  auto stats = optimizer.GetStats();
  EXPECT_DOUBLE_EQ(stats.prediction_accuracy, 0.8);
}

TEST_F(UXOptimizerTest, RollbackCount) {
  UXOptimizer optimizer;
  
  optimizer.IncrementRollbackCount();
  optimizer.IncrementRollbackCount();
  
  auto stats = optimizer.GetStats();
  EXPECT_EQ(stats.rollback_count, 2);
}

TEST_F(UXOptimizerTest, Reset) {
  UXOptimizer optimizer;
  
  optimizer.RecordInputLatency(50.0);
  optimizer.RecordFrameTime(16.67);
  optimizer.IncrementRollbackCount();
  
  optimizer.Reset();
  
  auto stats = optimizer.GetStats();
  EXPECT_DOUBLE_EQ(stats.avg_input_latency_ms, 0.0);
  EXPECT_EQ(stats.rollback_count, 0);
}

TEST_F(UXOptimizerTest, QualityRecommendation) {
  UXOptimizer optimizer;
  
  // Excellent network - no changes needed
  for (int i = 0; i < 10; ++i) {
    optimizer.RecordInputLatency(30.0);
    optimizer.RecordPacketLoss(0.0);
    optimizer.RecordFrameTime(16.67);
  }
  
  auto rec = optimizer.GetQualityRecommendation();
  EXPECT_FALSE(rec.reduce_render_quality);
  EXPECT_FALSE(rec.reduce_network_frequency);
  EXPECT_FALSE(rec.increase_prediction);
  EXPECT_EQ(rec.max_predict_ahead, 3);
  EXPECT_FLOAT_EQ(rec.render_scale, 1.0f);
  
  // Reset and test poor network
  optimizer.Reset();
  for (int i = 0; i < 10; ++i) {
    optimizer.RecordInputLatency(180.0);
    optimizer.RecordPacketLoss(0.04);
    optimizer.RecordFrameTime(25.0);
  }
  
  rec = optimizer.GetQualityRecommendation();
  EXPECT_TRUE(rec.reduce_render_quality);
  EXPECT_TRUE(rec.reduce_network_frequency);
  EXPECT_TRUE(rec.increase_prediction);
  EXPECT_GE(rec.max_predict_ahead, 4);
  EXPECT_LT(rec.render_scale, 1.0f);
}

class InputLatencyTrackerTest : public ::testing::Test {};

TEST_F(InputLatencyTrackerTest, BasicTracking) {
  InputLatencyTracker tracker;
  
  auto now = std::chrono::steady_clock::now();
  
  // Record input and confirmation
  tracker.RecordInputTime(100, now);
  tracker.RecordConfirmation(100, now + std::chrono::milliseconds(50));
  
  EXPECT_NEAR(tracker.GetAverageLatencyMs(), 50.0, 1.0);
}

TEST_F(InputLatencyTrackerTest, P95Latency) {
  InputLatencyTracker tracker;
  
  auto now = std::chrono::steady_clock::now();
  
  // Record 100 samples with increasing latency
  for (int i = 0; i < 100; ++i) {
    auto input_time = now + std::chrono::milliseconds(i * 10);
    auto confirm_time = input_time + std::chrono::milliseconds(10 + i);
    tracker.RecordInputTime(i, input_time);
    tracker.RecordConfirmation(i, confirm_time);
  }
  
  // P95 should be around 10 + 95 = 105ms
  double p95 = tracker.GetP95LatencyMs();
  EXPECT_NEAR(p95, 105.0, 10.0);
}

TEST_F(InputLatencyTrackerTest, Cleanup) {
  InputLatencyTracker tracker;
  
  auto now = std::chrono::steady_clock::now();
  
  // Record old entries
  for (int i = 0; i < 200; ++i) {
    tracker.RecordInputTime(i, now);
  }
  
  // Cleanup old entries
  tracker.Cleanup(200, 100);
  
  // Should have at most 100 entries
  // (we can't directly check size, but we can verify no crash)
}
