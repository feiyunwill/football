// Copyright 2026 Google LLC & Contributors
// Integration test for Phase 16 advanced frame sync features (ms-16.9).
//
// Tests all new modules working together:
// 1. Interpolation/Extrapolation
// 2. Deterministic PRNG
// 3. State Delta Codec
// 4. Prediction Accuracy Tracker
// 5. Adaptive Prediction Cap
// 6. Replay System
// 7. Adaptive Jitter Buffer

#include "frame_sync/interpolator.hpp"
#include "frame_sync/deterministic_prng.hpp"
#include "frame_sync/state_delta_codec.hpp"
#include "frame_sync/prediction_accuracy_tracker.hpp"
#include "frame_sync/adaptive_prediction_cap.hpp"
#include "frame_sync/replay_system.hpp"
#include "frame_sync/adaptive_jitter_buffer.hpp"
#include "frame_sync/protocol.hpp"

#include <gtest/gtest.h>
#include <string>
#include <vector>

namespace frame_sync {
namespace {

// ============================================================
// 1. Interpolation/Extrapolation Integration
// ============================================================

class InterpolationExtrapolationTest : public ::testing::Test {
 protected:
  void SetUp() override {
    // Simulate 3 frames of entity movement
    interp_.SaveState(0.0f);
    interp_.SavePosition(0, Vec3(0.0f, 0.0f, 0.0f));
    interp_.SavePosition(1, Vec3(10.0f, 0.0f, 0.0f));
    
    interp_.SaveState(0.1f);
    interp_.SavePosition(0, Vec3(1.0f, 0.0f, 0.0f));
    interp_.SavePosition(1, Vec3(9.0f, 0.0f, 0.0f));
  }

  Interpolator interp_;
};

TEST_F(InterpolationExtrapolationTest, InterpolationWorks) {
  auto state = interp_.GetInterpolatedState(0, 0.05f, 0.1f);
  EXPECT_NEAR(state.position.x, 0.5f, 0.01f);
  EXPECT_FALSE(state.is_extrapolated);
}

TEST_F(InterpolationExtrapolationTest, ExtrapolationWorks) {
  auto state = interp_.GetExtrapolatedState(0, 0.2f, 0.1f);
  EXPECT_NEAR(state.position.x, 2.0f, 0.1f);
  EXPECT_TRUE(state.is_extrapolated);
}

TEST_F(InterpolationExtrapolationTest, MultipleEntities) {
  auto s0 = interp_.GetInterpolatedState(0, 0.05f, 0.1f);
  auto s1 = interp_.GetInterpolatedState(1, 0.05f, 0.1f);
  
  EXPECT_NEAR(s0.position.x, 0.5f, 0.01f);
  EXPECT_NEAR(s1.position.x, 9.5f, 0.01f);
}

TEST_F(InterpolationExtrapolationTest, BoundsRespected) {
  ExtrapolationBounds bounds;
  bounds.max_distance = 0.5f;
  bounds.max_speed = 200.0f;
  bounds.max_extrapolation_time = 10.0f;
  
  auto state = interp_.GetExtrapolatedState(0, 1.0f, 0.1f, bounds);
  float distance = (state.position - Vec3(1.0f, 0.0f, 0.0f)).length();
  EXPECT_LE(distance, bounds.max_distance + 0.01f);
}

// ============================================================
// 2. Deterministic PRNG Integration
// ============================================================

TEST(DeterministicPRNGIntegration, CrossPlatformConsistency) {
  DeterministicPRNG prng1(12345);
  DeterministicPRNG prng2(12345);
  
  // Both PRNGs with same seed should produce identical sequences
  for (int i = 0; i < 100; ++i) {
    EXPECT_EQ(prng1.next(), prng2.next());
  }
}

TEST(DeterministicPRNGIntegration, DifferentSeedsDifferentOutput) {
  DeterministicPRNG prng1(11111);
  DeterministicPRNG prng2(22222);
  
  bool any_different = false;
  for (int i = 0; i < 10; ++i) {
    if (prng1.next() != prng2.next()) {
      any_different = true;
      break;
    }
  }
  EXPECT_TRUE(any_different);
}

TEST(DeterministicPRNGIntegration, DeterministicFromSeed) {
  // Two PRNGs with same seed should produce identical sequences
  DeterministicPRNG prng1(12345);
  DeterministicPRNG prng2(12345);
  
  // Generate 10 values from each
  std::vector<uint64_t> seq1, seq2;
  for (int i = 0; i < 10; ++i) {
    seq1.push_back(prng1.next());
    seq2.push_back(prng2.next());
  }
  
  EXPECT_EQ(seq1, seq2);
}

// ============================================================
// 3. State Delta Codec Integration
// ============================================================

TEST(StateDeltaCodecIntegration, MultiFrameRoundtrip) {
  StateDeltaCodec encoder;
  StateDeltaCodec decoder;
  
  // Simulate game state changes
  std::string state1 = "AAAAAAAAAAAAAAAA";  // 16 bytes
  std::string state2 = "BBBBBBBBBBBBBBBB";
  std::string state3 = "CCCCCCCCCCCCCCCC";
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  
  // Encode/decode frame 2
  std::string delta1 = encoder.EncodeDelta(state2);
  std::string decoded1 = decoder.DecodeDelta(delta1);
  EXPECT_EQ(decoded1, state2);
  
  // Encode/decode frame 3
  std::string delta2 = encoder.EncodeDelta(state3);
  std::string decoded2 = decoder.DecodeDelta(delta2);
  EXPECT_EQ(decoded2, state3);
}

TEST(StateDeltaCodecIntegration, CompressionEfficiency) {
  StateDeltaCodec encoder;
  StateDeltaCodec decoder;
  
  // Large state with small changes
  std::string state1(10000, 'A');
  std::string state2 = state1;
  state2[5000] = 'B';  // Single byte change
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  
  std::string delta = encoder.EncodeDelta(state2);
  std::string decoded = decoder.DecodeDelta(delta);
  
  EXPECT_EQ(decoded, state2);
  // Delta should be much smaller than full state
  EXPECT_LT(delta.size(), state1.size() / 2);
}

// ============================================================
// 4. Prediction Accuracy Tracker Integration
// ============================================================

TEST(PredictionAccuracyIntegration, AccuracyTracking) {
  PredictionAccuracyTracker tracker;
  
  // Simulate predictions and authoritative frames
  for (uint32_t i = 0; i < 100; ++i) {
    uint64_t predicted = (i % 10 == 0) ? 0xAAAA : 0xBBBB;  // 10% wrong
    tracker.RecordPrediction(i, predicted);
    tracker.RecordAuthoritative(i, 0xBBBB);
  }
  
  // Should be ~90% accurate
  double accuracy = tracker.GetAccuracy();
  EXPECT_NEAR(accuracy, 0.9, 0.05);
}

TEST(PredictionAccuracyIntegration, TrendDetection) {
  PredictionAccuracyTracker tracker;
  
  // First 50 frames: all correct
  for (uint32_t i = 0; i < 50; ++i) {
    tracker.RecordPrediction(i, 0xAAAA);
    tracker.RecordAuthoritative(i, 0xAAAA);
  }
  
  // Last 50 frames: all wrong
  for (uint32_t i = 50; i < 100; ++i) {
    tracker.RecordPrediction(i, 0xBBBB);
    tracker.RecordAuthoritative(i, 0xCCCC);
  }
  
  auto trend = tracker.GetAccuracyTrend();
  EXPECT_EQ(trend, PredictionAccuracyTracker::Trend::kDegrading);
}

// ============================================================
// 5. Adaptive Prediction Cap Integration
// ============================================================

TEST(AdaptivePredictionCapIntegration, RTTBasedScaling) {
  AdaptivePredictionCap cap;
  
  // Low RTT → low prediction
  cap.UpdateNetworkConditions(20.0, 0.0);
  EXPECT_EQ(cap.GetMaxPredictAhead(), 1);
  
  // High RTT → high prediction
  cap.UpdateNetworkConditions(150.0, 0.0);
  EXPECT_GE(cap.GetMaxPredictAhead(), 4);
}

TEST(AdaptivePredictionCapIntegration, PacketLossReducesPrediction) {
  AdaptivePredictionCap cap;
  
  cap.UpdateNetworkConditions(100.0, 0.0);
  int base = cap.GetMaxPredictAhead();
  
  cap.UpdateNetworkConditions(100.0, 0.08);
  int with_loss = cap.GetMaxPredictAhead();
  
  EXPECT_LE(with_loss, base);
}

TEST(AdaptivePredictionCapIntegration, AccuracyReducesPrediction) {
  AdaptivePredictionCap cap;
  
  cap.UpdateNetworkConditions(100.0, 0.0);
  cap.UpdatePredictionAccuracy(1.0);
  int perfect = cap.GetMaxPredictAhead();
  
  cap.UpdatePredictionAccuracy(0.6);
  int poor = cap.GetMaxPredictAhead();
  
  EXPECT_LE(poor, perfect);
}

// ============================================================
// 6. Replay System Integration
// ============================================================

TEST(ReplaySystemIntegration, FullReplayCycle) {
  ReplayRecorder recorder;
  ReplayPlayer player;
  
  // Record a game
  recorder.StartRecording(42, "integration_test", 2);
  
  for (uint32_t i = 0; i < 50; ++i) {
    std::vector<SlotInput> inputs(2);
    inputs[0].dir_x = static_cast<float>(i) * 0.1f;
    inputs[0].dir_y = static_cast<float>(i) * 0.2f;
    inputs[1].dir_x = static_cast<float>(i) * 0.3f;
    recorder.RecordFrame(i, i * 100, inputs);
  }
  
  recorder.StopRecording();
  
  // Load and play
  EXPECT_TRUE(player.LoadReplay(recorder.Serialize()));
  EXPECT_TRUE(player.IsLoaded());
  
  player.Play();
  EXPECT_TRUE(player.IsPlaying());
  
  // Verify all frames
  for (uint32_t i = 0; i < 50; ++i) {
    auto frame = player.GetCurrentFrame();
    ASSERT_TRUE(frame.has_value());
    EXPECT_EQ(frame->frame_number, i);
    EXPECT_EQ(frame->state_hash, i * 100);
    EXPECT_FLOAT_EQ(frame->inputs[0].dir_x, static_cast<float>(i) * 0.1f);
    
    if (i < 49) {
      EXPECT_TRUE(player.Advance());
    }
  }
  
  EXPECT_TRUE(player.IsAtEnd());
  EXPECT_FALSE(player.Advance());
}

TEST(ReplaySystemIntegration, SeekWorks) {
  ReplayRecorder recorder;
  
  recorder.StartRecording(42, "seek_test", 1);
  for (uint32_t i = 0; i < 100; ++i) {
    std::vector<SlotInput> inputs(1);
    inputs[0].dir_x = static_cast<float>(i);
    recorder.RecordFrame(i, i * 100, inputs);
  }
  recorder.StopRecording();
  
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(recorder.Serialize()));
  
  // Seek to frame 50
  EXPECT_TRUE(player.SeekToFrame(50));
  auto frame = player.GetCurrentFrame();
  ASSERT_TRUE(frame.has_value());
  EXPECT_EQ(frame->frame_number, 50u);
  EXPECT_FLOAT_EQ(frame->inputs[0].dir_x, 50.0f);
}

// ============================================================
// 7. Adaptive Jitter Buffer Integration
// ============================================================

TEST(AdaptiveJitterBufferIntegration, JitterIncreasesBuffer) {
  AdaptiveJitterBuffer buffer;
  
  buffer.Update(5.0, 50.0);
  int low_jitter = buffer.GetRecommendedBufferFrames();
  
  buffer.Reset();
  buffer.Update(50.0, 50.0);
  int high_jitter = buffer.GetRecommendedBufferFrames();
  
  EXPECT_GE(high_jitter, low_jitter);
}

TEST(AdaptiveJitterBufferIntegration, RTTIncreasesBuffer) {
  AdaptiveJitterBuffer buffer;
  
  buffer.Update(20.0, 30.0);
  int low_rtt = buffer.GetRecommendedBufferFrames();
  
  buffer.Reset();
  buffer.Update(20.0, 150.0);
  int high_rtt = buffer.GetRecommendedBufferFrames();
  
  EXPECT_GE(high_rtt, low_rtt);
}

TEST(AdaptiveJitterBufferIntegration, FrameDropDecision) {
  AdaptiveJitterBuffer buffer;
  buffer.Update(10.0, 50.0);
  
  int buffer_frames = buffer.GetRecommendedBufferFrames();
  uint32_t current = 100;
  
  // Recent frame: don't drop
  EXPECT_FALSE(buffer.ShouldDropFrame(current - 1, current));
  
  // Very old frame: drop
  EXPECT_TRUE(buffer.ShouldDropFrame(current - buffer_frames * 3, current));
}

// ============================================================
// 8. Combined Module Integration
// ============================================================

TEST(CombinedIntegration, FullPipeline) {
  // Simulate a client pipeline with all modules
  
  // 1. Record replay
  ReplayRecorder recorder;
  recorder.StartRecording(42, "pipeline_test", 1);
  
  // 2. Create all modules
  DeterministicPRNG prng(42);
  Interpolator interp;
  PredictionAccuracyTracker tracker;
  AdaptivePredictionCap cap;
  AdaptiveJitterBuffer jitter;
  StateDeltaCodec encoder, decoder;
  
  // 3. Simulate 100 frames
  std::string prev_state(100, 'A');
  encoder.SetBaseline(prev_state);
  decoder.SetBaseline(prev_state);
  
  for (uint32_t i = 0; i < 100; ++i) {
    // Generate state
    std::string state = prev_state;
    state[0] = static_cast<char>('A' + (i % 26));
    
    // Record replay
    std::vector<SlotInput> inputs(1);
    inputs[0].dir_x = static_cast<float>(i) * 0.1f;
    recorder.RecordFrame(i, prng.next(), inputs);
    
    // Delta compress
    std::string delta = encoder.EncodeDelta(state);
    std::string decoded = decoder.DecodeDelta(delta);
    EXPECT_EQ(decoded, state);
    
    // Track prediction
    uint64_t predicted = prng.next();
    tracker.RecordPrediction(i, predicted);
    (void)tracker.RecordAuthoritative(i, predicted);  // All correct
    
    // Update adaptive modules
    double jitter_ms = 10.0 + (i % 5) * 2.0;
    cap.UpdateNetworkConditions(50.0 + i, 0.0);
    cap.UpdatePredictionAccuracy(tracker.GetRecentAccuracy());
    jitter.Update(jitter_ms, 50.0 + i);
    
    // Interpolation
    interp.SaveState(static_cast<float>(i) * 0.1f);
    interp.SavePosition(0, Vec3(static_cast<float>(i), 0.0f, 0.0f));
    
    prev_state = state;
  }
  
  recorder.StopRecording();
  
  // 4. Verify all modules
  EXPECT_DOUBLE_EQ(tracker.GetAccuracy(), 1.0);
  EXPECT_GE(cap.GetMaxPredictAhead(), 1);
  EXPECT_GE(jitter.GetRecommendedBufferFrames(), 1);
  
  // 5. Play replay
  ReplayPlayer player;
  EXPECT_TRUE(player.LoadReplay(recorder.Serialize()));
  player.Play();
  EXPECT_TRUE(player.IsPlaying());
  
  // Verify replay frames match
  for (uint32_t i = 0; i < 100; ++i) {
    auto frame = player.GetCurrentFrame();
    ASSERT_TRUE(frame.has_value());
    EXPECT_EQ(frame->frame_number, i);
    if (i < 99) EXPECT_TRUE(player.Advance());
  }
}

// ============================================================
// 9. Performance Regression Test
// ============================================================

TEST(PerformanceTest, DeltaCodecThroughput) {
  StateDeltaCodec encoder;
  StateDeltaCodec decoder;
  
  std::string state1(10000, 'A');
  std::string state2 = state1;
  state2[5000] = 'B';
  
  encoder.SetBaseline(state1);
  decoder.SetBaseline(state1);
  
  // Measure encode/decode time
  auto start = std::chrono::steady_clock::now();
  
  for (int i = 0; i < 1000; ++i) {
    std::string delta = encoder.EncodeDelta(state2);
    std::string decoded = decoder.DecodeDelta(delta);
    EXPECT_EQ(decoded, state2);
  }
  
  auto end = std::chrono::steady_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start);
  
  // Should complete 1000 encode/decode cycles in < 100ms
  EXPECT_LT(duration.count(), 100);
}

TEST(PerformanceTest, InterpolationThroughput) {
  Interpolator interp;
  
  // Set up 100 entities
  interp.SaveState(0.0f);
  for (int i = 0; i < 100; ++i) {
    interp.SavePosition(i, Vec3(static_cast<float>(i), 0.0f, 0.0f));
  }
  
  interp.SaveState(0.1f);
  for (int i = 0; i < 100; ++i) {
    interp.SavePosition(i, Vec3(static_cast<float>(i) + 1.0f, 0.0f, 0.0f));
  }
  
  // Measure interpolation time
  auto start = std::chrono::steady_clock::now();
  
  for (int i = 0; i < 1000; ++i) {
    for (int j = 0; j < 100; ++j) {
      auto state = interp.GetInterpolatedState(j, 0.05f, 0.1f);
      EXPECT_FALSE(state.is_extrapolated);
    }
  }
  
  auto end = std::chrono::steady_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start);
  
  // Should complete 100,000 interpolations in < 50ms
  EXPECT_LT(duration.count(), 50);
}

}  // namespace
}  // namespace frame_sync
