// Copyright 2026 Google LLC & Contributors
// Unit tests for LatencyCompensator (ms-17.1)

#include "frame_sync/latency_compensator.hpp"

#include <gtest/gtest.h>

namespace frame_sync {
namespace {

// Test basic RTT recording
TEST(LatencyCompensatorTest, BasicRTT) {
  LatencyCompensator comp;
  
  comp.RecordRTT(100.0, 150.0);  // 50ms RTT
  
  EXPECT_DOUBLE_EQ(comp.GetSmoothedRTT(), 50.0);
  EXPECT_DOUBLE_EQ(comp.GetEstimatedOneWay(), 25.0);
}

// Test multiple RTT samples
TEST(LatencyCompensatorTest, MultipleSamples) {
  LatencyCompensator comp;
  
  comp.RecordRTT(100.0, 140.0);  // 40ms
  comp.RecordRTT(200.0, 250.0);  // 50ms
  comp.RecordRTT(300.0, 345.0);  // 45ms
  
  double rtt = comp.GetSmoothedRTT();
  EXPECT_GT(rtt, 40.0);
  EXPECT_LT(rtt, 50.0);
}

// Test jitter calculation
TEST(LatencyCompensatorTest, JitterCalculation) {
  LatencyCompensator comp;
  
  // Consistent RTT → low jitter
  comp.RecordRTT(100.0, 150.0);
  comp.RecordRTT(200.0, 250.0);
  comp.RecordRTT(300.0, 350.0);
  
  double jitter1 = comp.GetJitter();
  EXPECT_LT(jitter1, 1.0);
  
  // Variable RTT → higher jitter
  LatencyCompensator comp2;
  comp2.RecordRTT(100.0, 130.0);  // 30ms
  comp2.RecordRTT(200.0, 270.0);  // 70ms
  comp2.RecordRTT(300.0, 340.0);  // 40ms
  
  double jitter2 = comp2.GetJitter();
  EXPECT_GT(jitter2, jitter1);
}

// Test adjusted offset
TEST(LatencyCompensatorTest, AdjustedOffset) {
  LatencyCompensator comp;
  
  comp.RecordRTT(100.0, 150.0);  // 50ms RTT, 25ms one-way
  
  double offset = comp.GetAdjustedOffset();
  EXPECT_GE(offset, 25.0);  // At least one-way
  EXPECT_LT(offset, 50.0);  // Less than full RTT
}

// Test min/max RTT
TEST(LatencyCompensatorTest, MinMaxRTT) {
  LatencyCompensator comp;
  
  comp.RecordRTT(100.0, 130.0);  // 30ms
  comp.RecordRTT(200.0, 270.0);  // 70ms
  comp.RecordRTT(300.0, 345.0);  // 45ms
  
  EXPECT_DOUBLE_EQ(comp.GetMinRTT(), 30.0);
  EXPECT_DOUBLE_EQ(comp.GetMaxRTT(), 70.0);
}

// Test active status
TEST(LatencyCompensatorTest, ActiveStatus) {
  LatencyCompensator comp;
  
  EXPECT_FALSE(comp.IsActive());
  
  for (int i = 0; i < 5; ++i) {
    comp.RecordRTT(100.0 + i * 100, 150.0 + i * 100);
  }
  
  EXPECT_TRUE(comp.IsActive());
}

// Test reset
TEST(LatencyCompensatorTest, Reset) {
  LatencyCompensator comp;
  
  comp.RecordRTT(100.0, 150.0);
  EXPECT_DOUBLE_EQ(comp.GetSmoothedRTT(), 50.0);
  
  comp.Reset();
  EXPECT_DOUBLE_EQ(comp.GetSmoothedRTT(), 0.0);
}

// Test compensation status
TEST(LatencyCompensatorTest, CompensationStatus) {
  LatencyCompensator comp;
  
  comp.RecordRTT(100.0, 150.0);
  comp.RecordRTT(200.0, 255.0);
  
  auto status = comp.GetStatus();
  EXPECT_GT(status.smoothed_rtt_ms, 0.0);
  EXPECT_GT(status.estimated_oneway_ms, 0.0);
  EXPECT_GE(status.sample_count, 2u);
}

// Test with server timestamp
TEST(LatencyCompensatorTest, ServerTimestamp) {
  LatencyCompensator comp;
  
  // Simulate: send at 100ms, server receives at 120ms, client receives at 150ms
  comp.RecordRoundTrip(100.0, 120.0, 150.0);
  
  EXPECT_DOUBLE_EQ(comp.GetSmoothedRTT(), 50.0);
  // One-way should account for server processing time
  double oneway = comp.GetEstimatedOneWay();
  EXPECT_GT(oneway, 20.0);  // At least server - send
  EXPECT_LT(oneway, 30.0);  // Less than recv - server
}

// Test negative RTT handling
TEST(LatencyCompensatorTest, NegativeRTT) {
  LatencyCompensator comp;
  
  // Invalid measurement (recv before send)
  comp.RecordRTT(200.0, 100.0);
  
  EXPECT_DOUBLE_EQ(comp.GetSmoothedRTT(), 0.0);
}

// Test weighted average
TEST(LatencyCompensatorTest, WeightedAverage) {
  LatencyCompensator comp;
  
  // Recent samples should have more weight
  comp.RecordRTT(100.0, 200.0);  // 100ms (old)
  comp.RecordRTT(200.0, 250.0);  // 50ms (recent)
  comp.RecordRTT(300.0, 350.0);  // 50ms (recent)
  
  double rtt = comp.GetSmoothedRTT();
  // Should be closer to 50ms than 100ms
  EXPECT_LT(rtt, 75.0);
}

}  // namespace
}  // namespace frame_sync
