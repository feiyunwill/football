// Copyright 2026 Google LLC & Contributors
// Unit tests for Interpolator extrapolation (ms-16.3)

#include "frame_sync/interpolator.hpp"

#include <gtest/gtest.h>

namespace frame_sync {
namespace {

// Test basic interpolation (existing functionality)
TEST(InterpolatorTest, BasicInterpolation) {
  Interpolator interp;
  
  // Save two frames
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.0f, 0.0f, 0.0f));
  
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(1.0f, 0.0f, 0.0f));
  
  // Interpolate at midpoint
  auto state = interp.GetInterpolatedState(0, 0.05f, 0.1f);
  
  EXPECT_NEAR(state.position.x, 0.5f, 0.01f);
  EXPECT_FALSE(state.is_extrapolated);
}

// Test extrapolation basic
TEST(InterpolatorTest, BasicExtrapolation) {
  Interpolator interp;
  
  // Save two frames
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.0f, 0.0f, 0.0f));
  
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(1.0f, 0.0f, 0.0f));  // Moving at 10 m/s
  
  // Extrapolate ahead
  auto state = interp.GetExtrapolatedState(0, 0.2f, 0.1f);
  
  // Should be at ~2.0 (1.0 + 10 m/s * 0.1s)
  EXPECT_NEAR(state.position.x, 2.0f, 0.1f);
  EXPECT_TRUE(state.is_extrapolated);
}

// Test extrapolation bounds - max distance
TEST(InterpolatorTest, ExtrapolationBoundsMaxDistance) {
  Interpolator interp;
  
  // Save two frames with high velocity
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.0f, 0.0f, 0.0f));
  
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(10.0f, 0.0f, 0.0f));  // Moving at 100 m/s
  
  ExtrapolationBounds bounds;
  bounds.max_distance = 2.0f;
  bounds.max_speed = 200.0f;  // Allow high speed
  
  // Extrapolate far ahead
  auto state = interp.GetExtrapolatedState(0, 1.0f, 0.1f, bounds);
  
  // Should be clamped to max_distance
  float distance = (state.position - Vec3(10.0f, 0.0f, 0.0f)).length();
  EXPECT_LE(distance, bounds.max_distance + 0.01f);
}

// Test extrapolation bounds - max speed
TEST(InterpolatorTest, ExtrapolationBoundsMaxSpeed) {
  Interpolator interp;
  
  // Save two frames with very high velocity
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.0f, 0.0f, 0.0f));
  
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(50.0f, 0.0f, 0.0f));  // Moving at 500 m/s
  
  ExtrapolationBounds bounds;
  bounds.max_speed = 20.0f;  // Clamp to 20 m/s
  
  // Extrapolate 0.1s ahead
  auto state = interp.GetExtrapolatedState(0, 0.2f, 0.1f, bounds);
  
  // Current position is 50, velocity clamped to 20 m/s, extrapolate 0.1s
  // Position: 50 + 20 * 0.1 = 52
  EXPECT_NEAR(state.position.x, 52.0f, 0.1f);
}

// Test extrapolation bounds - max time
TEST(InterpolatorTest, ExtrapolationBoundsMaxTime) {
  Interpolator interp;
  
  // Save two frames
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.0f, 0.0f, 0.0f));
  
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(1.0f, 0.0f, 0.0f));  // Moving at 10 m/s
  
  ExtrapolationBounds bounds;
  bounds.max_extrapolation_time = 0.2f;
  
  // Extrapolate way ahead
  auto state = interp.GetExtrapolatedState(0, 1.0f, 0.1f, bounds);
  
  // Should be clamped to max_extrapolation_time
  // Position: 1.0 + 10 * 0.2 = 3.0
  EXPECT_NEAR(state.position.x, 3.0f, 0.1f);
}

// Test extrapolation not needed (behind current frame)
TEST(InterpolatorTest, ExtrapolationNotNeeded) {
  Interpolator interp;
  
  // Save two frames
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.0f, 0.0f, 0.0f));
  
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(1.0f, 0.0f, 0.0f));
  
  // Request time behind current frame - should interpolate, not extrapolate
  auto state = interp.GetExtrapolatedState(0, 0.05f, 0.1f);
  
  EXPECT_NEAR(state.position.x, 0.5f, 0.01f);
  EXPECT_FALSE(state.is_extrapolated);
}

// Test NeedsExtrapolation
TEST(InterpolatorTest, NeedsExtrapolation) {
  Interpolator interp;
  
  interp.SaveState(0.1f);
  
  EXPECT_FALSE(interp.NeedsExtrapolation(0.05f));
  EXPECT_FALSE(interp.NeedsExtrapolation(0.1f));
  EXPECT_TRUE(interp.NeedsExtrapolation(0.15f));
}

// Test extrapolation with zero velocity
TEST(InterpolatorTest, ExtrapolationZeroVelocity) {
  Interpolator interp;
  
  // Save two frames with same position (stationary)
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(5.0f, 5.0f, 0.0f));
  
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(5.0f, 5.0f, 0.0f));
  
  // Extrapolate - should stay at same position
  auto state = interp.GetExtrapolatedState(0, 0.2f, 0.1f);
  
  EXPECT_NEAR(state.position.x, 5.0f, 0.01f);
  EXPECT_NEAR(state.position.y, 5.0f, 0.01f);
  EXPECT_TRUE(state.is_extrapolated);
}

// Test extrapolation with multiple entities
TEST(InterpolatorTest, ExtrapolationMultipleEntities) {
  Interpolator interp;
  
  // Save two frames with two entities
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.0f, 0.0f, 0.0f));
  interp.SavePosition(1, Vec3(10.0f, 0.0f, 0.0f));
  
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(1.0f, 0.0f, 0.0f));   // Moving right
  interp.SavePosition(1, Vec3(9.0f, 0.0f, 0.0f));    // Moving left
  
  // Extrapolate both
  auto state0 = interp.GetExtrapolatedState(0, 0.2f, 0.1f);
  auto state1 = interp.GetExtrapolatedState(1, 0.2f, 0.1f);
  
  EXPECT_NEAR(state0.position.x, 2.0f, 0.1f);
  EXPECT_NEAR(state1.position.x, 8.0f, 0.1f);
}

// Test extrapolation corner case - only one frame saved
TEST(InterpolatorTest, ExtrapolationSingleFrame) {
  Interpolator interp;
  
  // Save only one frame
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(5.0f, 0.0f, 0.0f));
  
  // Extrapolate - should use current position (no velocity to extrapolate)
  auto state = interp.GetExtrapolatedState(0, 0.2f, 0.1f);
  
  EXPECT_NEAR(state.position.x, 5.0f, 0.01f);
  EXPECT_TRUE(state.is_extrapolated);
}

// Test extrapolation timestamp
TEST(InterpolatorTest, ExtrapolationTimestamp) {
  Interpolator interp;
  
  interp.SaveState(0.0f);
  interp.SavePosition(0, Vec3(0.0f, 0.0f, 0.0f));
  
  interp.SaveState(0.1f);
  interp.SavePosition(0, Vec3(1.0f, 0.0f, 0.0f));
  
  float render_time = 0.25f;
  auto state = interp.GetExtrapolatedState(0, render_time, 0.1f);
  
  EXPECT_FLOAT_EQ(state.timestamp, render_time);
}

}  // namespace
}  // namespace frame_sync
