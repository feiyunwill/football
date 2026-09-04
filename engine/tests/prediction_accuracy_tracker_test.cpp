// Copyright 2026 Google LLC & Contributors
// Unit tests for PredictionAccuracyTracker (ms-16.5)

#include "frame_sync/prediction_accuracy_tracker.hpp"

#include <gtest/gtest.h>

namespace frame_sync {
namespace {

// Test basic prediction tracking
TEST(PredictionAccuracyTrackerTest, BasicTracking) {
  PredictionAccuracyTracker tracker;
  
  // Record predictions
  tracker.RecordPrediction(1, 0x1234);
  tracker.RecordPrediction(2, 0x5678);
  tracker.RecordPrediction(3, 0x9ABC);
  
  // Record authoritative hashes
  auto r1 = tracker.RecordAuthoritative(1, 0x1234);  // Correct
  auto r2 = tracker.RecordAuthoritative(2, 0x9999);  // Wrong
  auto r3 = tracker.RecordAuthoritative(3, 0x9ABC);  // Correct
  
  EXPECT_TRUE(r1.has_value() && *r1);
  EXPECT_TRUE(r2.has_value() && !*r2);
  EXPECT_TRUE(r3.has_value() && *r3);
  
  EXPECT_DOUBLE_EQ(tracker.GetAccuracy(), 2.0 / 3.0);
  EXPECT_EQ(tracker.GetTotalFrames(), 3u);
  EXPECT_EQ(tracker.GetCorrectFrames(), 2u);
}

// Test accuracy without predictions
TEST(PredictionAccuracyTrackerTest, NoPrediction) {
  PredictionAccuracyTracker tracker;
  
  auto r = tracker.RecordAuthoritative(1, 0x1234);
  EXPECT_FALSE(r.has_value());  // No prediction recorded
  EXPECT_DOUBLE_EQ(tracker.GetAccuracy(), 1.0);  // Default to 1.0
}

// Test recent accuracy window
TEST(PredictionAccuracyTrackerTest, RecentAccuracy) {
  PredictionAccuracyTracker tracker;
  
  // Record 100 frames: first 50 correct, last 50 wrong
  for (uint32_t i = 0; i < 50; ++i) {
    tracker.RecordPrediction(i, 0xAAAA);
    tracker.RecordAuthoritative(i, 0xAAAA);
  }
  for (uint32_t i = 50; i < 100; ++i) {
    tracker.RecordPrediction(i, 0xBBBB);
    tracker.RecordAuthoritative(i, 0xCCCC);
  }
  
  // Overall accuracy should be 50%
  EXPECT_DOUBLE_EQ(tracker.GetAccuracy(), 0.5);
  
  // Recent window (50 frames) should be 0%
  EXPECT_DOUBLE_EQ(tracker.GetRecentAccuracy(50), 0.0);
  
  // Recent window (100 frames) should be 50%
  EXPECT_DOUBLE_EQ(tracker.GetRecentAccuracy(100), 0.5);
}

// Test accuracy trend
TEST(PredictionAccuracyTrackerTest, AccuracyTrend) {
  PredictionAccuracyTracker tracker;
  
  // First half: all wrong
  for (uint32_t i = 0; i < 30; ++i) {
    tracker.RecordPrediction(i, 0xAAAA);
    tracker.RecordAuthoritative(i, 0xBBBB);
  }
  
  // Second half: all correct
  for (uint32_t i = 30; i < 60; ++i) {
    tracker.RecordPrediction(i, 0xCCCC);
    tracker.RecordAuthoritative(i, 0xCCCC);
  }
  
  auto trend = tracker.GetAccuracyTrend();
  EXPECT_EQ(trend, PredictionAccuracyTracker::Trend::kImproving);
}

// Test degrading trend
TEST(PredictionAccuracyTrackerTest, DegradingTrend) {
  PredictionAccuracyTracker tracker;
  
  // First half: all correct
  for (uint32_t i = 0; i < 30; ++i) {
    tracker.RecordPrediction(i, 0xAAAA);
    tracker.RecordAuthoritative(i, 0xAAAA);
  }
  
  // Second half: all wrong
  for (uint32_t i = 30; i < 60; ++i) {
    tracker.RecordPrediction(i, 0xBBBB);
    tracker.RecordAuthoritative(i, 0xCCCC);
  }
  
  auto trend = tracker.GetAccuracyTrend();
  EXPECT_EQ(trend, PredictionAccuracyTracker::Trend::kDegrading);
}

// Test pending predictions
TEST(PredictionAccuracyTrackerTest, PendingPredictions) {
  PredictionAccuracyTracker tracker;
  
  EXPECT_FALSE(tracker.HasPendingPredictions());
  EXPECT_EQ(tracker.GetPendingCount(), 0u);
  
  tracker.RecordPrediction(1, 0x1234);
  tracker.RecordPrediction(2, 0x5678);
  
  EXPECT_TRUE(tracker.HasPendingPredictions());
  EXPECT_EQ(tracker.GetPendingCount(), 2u);
  
  tracker.RecordAuthoritative(1, 0x1234);
  EXPECT_EQ(tracker.GetPendingCount(), 1u);
  
  tracker.RecordAuthoritative(2, 0x5678);
  EXPECT_FALSE(tracker.HasPendingPredictions());
}

// Test recent mismatches
TEST(PredictionAccuracyTrackerTest, RecentMismatches) {
  PredictionAccuracyTracker tracker;
  
  // Record some mismatches
  for (uint32_t i = 0; i < 25; ++i) {
    tracker.RecordPrediction(i, 0xAAAA);
    tracker.RecordAuthoritative(i, 0xBBBB);  // All wrong
  }
  
  const auto& mismatches = tracker.GetRecentMismatches();
  EXPECT_EQ(mismatches.size(), 20u);  // Capped at kMaxMismatches
  EXPECT_EQ(mismatches.front(), 5u);  // Oldest kept (0-4 were evicted)
  EXPECT_EQ(mismatches.back(), 24u);
}

// Test cleanup
TEST(PredictionAccuracyTrackerTest, Cleanup) {
  PredictionAccuracyTracker tracker;
  
  // Record predictions - cleanup happens automatically
  for (uint32_t i = 0; i < 200; ++i) {
    tracker.RecordPrediction(i, 0xAAAA);
  }
  
  // After recording 200 frames, older predictions get cleaned up
  // Should have roughly 100 pending (last 100 frames)
  EXPECT_GE(tracker.GetPendingCount(), 99u);
  EXPECT_LE(tracker.GetPendingCount(), 101u);
  
  // Record more frames to trigger more cleanup
  for (uint32_t i = 200; i < 210; ++i) {
    tracker.RecordPrediction(i, 0xBBBB);
    tracker.RecordAuthoritative(i - 200, 0xBBBB);
  }
  
  // Should have roughly 110 pending
  EXPECT_GE(tracker.GetPendingCount(), 100u);
  EXPECT_LE(tracker.GetPendingCount(), 115u);
}

// Test reset
TEST(PredictionAccuracyTrackerTest, Reset) {
  PredictionAccuracyTracker tracker;
  
  tracker.RecordPrediction(1, 0x1234);
  tracker.RecordAuthoritative(1, 0x5678);
  
  EXPECT_EQ(tracker.GetTotalFrames(), 1u);
  
  tracker.Reset();
  
  EXPECT_EQ(tracker.GetTotalFrames(), 0u);
  EXPECT_DOUBLE_EQ(tracker.GetAccuracy(), 1.0);
  EXPECT_FALSE(tracker.HasPendingPredictions());
}

// Test perfect accuracy
TEST(PredictionAccuracyTrackerTest, PerfectAccuracy) {
  PredictionAccuracyTracker tracker;
  
  for (uint32_t i = 0; i < 100; ++i) {
    tracker.RecordPrediction(i, i * 1000);
    tracker.RecordAuthoritative(i, i * 1000);
  }
  
  EXPECT_DOUBLE_EQ(tracker.GetAccuracy(), 1.0);
  EXPECT_EQ(tracker.GetTotalFrames(), 100u);
  EXPECT_EQ(tracker.GetCorrectFrames(), 100u);
}

// Test zero accuracy
TEST(PredictionAccuracyTrackerTest, ZeroAccuracy) {
  PredictionAccuracyTracker tracker;
  
  for (uint32_t i = 0; i < 100; ++i) {
    tracker.RecordPrediction(i, 0xAAAA);
    tracker.RecordAuthoritative(i, 0xBBBB);
  }
  
  EXPECT_DOUBLE_EQ(tracker.GetAccuracy(), 0.0);
}

}  // namespace
}  // namespace frame_sync
