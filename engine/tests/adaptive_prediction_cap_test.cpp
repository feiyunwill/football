// Copyright 2026 Google LLC & Contributors
// Unit tests for AdaptivePredictionCap (ms-16.6)

#include "frame_sync/adaptive_prediction_cap.hpp"

#include <gtest/gtest.h>

namespace frame_sync {
namespace {

// Test default values
TEST(AdaptivePredictionCapTest, DefaultValues) {
  AdaptivePredictionCap cap;
  
  // Default: low RTT, no loss, perfect accuracy
  int max_frames = cap.GetMaxPredictAhead();
  EXPECT_GE(max_frames, 1);
  EXPECT_LE(max_frames, 8);
}

// Test RTT-based scaling
TEST(AdaptivePredictionCapTest, RTTScaling) {
  AdaptivePredictionCap cap;
  
  // Low RTT → fewer prediction frames
  cap.UpdateNetworkConditions(20.0, 0.0);
  EXPECT_EQ(cap.GetMaxPredictAhead(), 1);
  
  // Medium RTT → moderate prediction
  cap.UpdateNetworkConditions(60.0, 0.0);
  EXPECT_EQ(cap.GetMaxPredictAhead(), 3);
  
  // High RTT → more prediction
  cap.UpdateNetworkConditions(150.0, 0.0);
  EXPECT_EQ(cap.GetMaxPredictAhead(), 5);
}

// Test packet loss adjustment
TEST(AdaptivePredictionCapTest, PacketLossAdjustment) {
  AdaptivePredictionCap cap;
  
  // High RTT but also high loss → reduce prediction
  cap.UpdateNetworkConditions(100.0, 0.0);
  int base_cap = cap.GetMaxPredictAhead();
  
  // Add packet loss
  cap.UpdateNetworkConditions(100.0, 0.08);
  int adjusted_cap = cap.GetMaxPredictAhead();
  
  EXPECT_LE(adjusted_cap, base_cap);
}

// Test accuracy adjustment
TEST(AdaptivePredictionCapTest, AccuracyAdjustment) {
  AdaptivePredictionCap cap;
  
  // Good conditions
  cap.UpdateNetworkConditions(100.0, 0.0);
  cap.UpdatePredictionAccuracy(1.0);
  int good_cap = cap.GetMaxPredictAhead();
  
  // Poor accuracy
  cap.UpdatePredictionAccuracy(0.6);
  int poor_cap = cap.GetMaxPredictAhead();
  
  EXPECT_LE(poor_cap, good_cap);
}

// Test frame stability adjustment
TEST(AdaptivePredictionCapTest, FrameStabilityAdjustment) {
  AdaptivePredictionCap cap;
  
  // Good conditions
  cap.UpdateNetworkConditions(100.0, 0.0);
  cap.UpdateFrameTime(16.67, 0.5);
  int stable_cap = cap.GetMaxPredictAhead();
  
  // High jitter
  cap.UpdateFrameTime(16.67, 5.0);
  int jittery_cap = cap.GetMaxPredictAhead();
  
  EXPECT_LE(jittery_cap, stable_cap);
}

// Test clamping
TEST(AdaptivePredictionCapTest, Clamping) {
  AdaptivePredictionCap cap;
  
  // Extreme conditions should still be in valid range
  cap.UpdateNetworkConditions(500.0, 0.5);
  cap.UpdatePredictionAccuracy(0.3);
  cap.UpdateFrameTime(100.0, 50.0);
  
  int max_frames = cap.GetMaxPredictAhead();
  EXPECT_GE(max_frames, 1);
  EXPECT_LE(max_frames, 8);
}

// Test cap summary
TEST(AdaptivePredictionCapTest, CapSummary) {
  AdaptivePredictionCap cap;
  
  cap.UpdateNetworkConditions(80.0, 0.02);
  cap.UpdatePredictionAccuracy(0.9);
  
  auto summary = cap.GetSummary();
  
  EXPECT_GE(summary.max_predict_ahead, 1);
  EXPECT_LE(summary.max_predict_ahead, 8);
  EXPECT_GE(summary.rtt_component, 1);
  EXPECT_LE(summary.rtt_component, 6);
  EXPECT_GT(summary.packet_loss_penalty, 0.0);
  EXPECT_LE(summary.packet_loss_penalty, 1.0);
  EXPECT_GT(summary.accuracy_penalty, 0.0);
  EXPECT_LE(summary.accuracy_penalty, 1.0);
}

// Test recommended bounds
TEST(AdaptivePredictionCapTest, RecommendedBounds) {
  AdaptivePredictionCap cap;
  
  cap.UpdateNetworkConditions(100.0, 0.0);
  cap.UpdatePredictionAccuracy(0.9);
  
  auto bounds = cap.GetRecommendedBounds();
  
  EXPECT_GT(bounds.max_distance, 0.0f);
  EXPECT_GT(bounds.max_speed, 0.0f);
  EXPECT_GT(bounds.max_time, 0.0f);
  EXPECT_GE(bounds.max_time, 0.1f);  // At least 1 frame
  EXPECT_LE(bounds.max_time, 0.8f);  // At most 8 frames
}

// Test reset
TEST(AdaptivePredictionCapTest, Reset) {
  AdaptivePredictionCap cap;
  
  cap.UpdateNetworkConditions(200.0, 0.1);
  cap.UpdatePredictionAccuracy(0.5);
  cap.UpdateFrameTime(50.0, 10.0);
  
  cap.Reset();
  
  // Should return to defaults
  int max_frames = cap.GetMaxPredictAhead();
  EXPECT_GE(max_frames, 1);
  EXPECT_LE(max_frames, 8);
}

// Test combined conditions
TEST(AdaptivePredictionCapTest, CombinedConditions) {
  AdaptivePredictionCap cap;
  
  // All good conditions
  cap.UpdateNetworkConditions(50.0, 0.0);
  cap.UpdatePredictionAccuracy(1.0);
  cap.UpdateFrameTime(16.67, 0.5);
  int good_cap = cap.GetMaxPredictAhead();
  
  // All poor conditions
  cap.UpdateNetworkConditions(150.0, 0.05);
  cap.UpdatePredictionAccuracy(0.7);
  cap.UpdateFrameTime(33.0, 5.0);
  int poor_cap = cap.GetMaxPredictAhead();
  
  EXPECT_LE(poor_cap, good_cap);
}

}  // namespace
}  // namespace frame_sync
