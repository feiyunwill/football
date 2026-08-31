// Copyright 2026 Google LLC & Contributors
// Frame interpolation for logic-render separation (ms-1.6).
// Provides temporal interpolation between logic frames for smooth rendering.

#ifndef GFOOTBALL_FRAME_SYNC_INTERPOLATOR_HPP
#define GFOOTBALL_FRAME_SYNC_INTERPOLATOR_HPP

#include <chrono>
#include <cmath>
#include <cstdint>
#include <functional>
#include <vector>

namespace frame_sync {

// Simple 3D vector for interpolation
struct Vec3 {
  float x = 0.f;
  float y = 0.f;
  float z = 0.f;

  Vec3() = default;
  Vec3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}

  Vec3 operator+(const Vec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
  Vec3 operator-(const Vec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
  Vec3 operator*(float s) const { return {x * s, y * s, z * s}; }

  float length_sq() const { return x * x + y * y + z * z; }
  float length() const { return std::sqrt(length_sq()); }

  Vec3 normalized() const {
    float len = length();
    if (len < 1e-6f) return {0.f, 0.f, 0.f};
    return *this * (1.f / len);
  }
};

// Simple quaternion for rotation interpolation
struct Quat {
  float x = 0.f;
  float y = 0.f;
  float z = 0.f;
  float w = 1.f;

  Quat() = default;
  Quat(float x_, float y_, float z_, float w_) : x(x_), y(y_), z(z_), w(w_) {}

  // Spherical linear interpolation (slerp)
  static Quat slerp(const Quat& a, const Quat& b, float t) {
    float dot = a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w;
    
    // If dot is negative, negate one quaternion to take the shorter path
    Quat b_adj = b;
    if (dot < 0.f) {
      b_adj = {-b.x, -b.y, -b.z, -b.w};
      dot = -dot;
    }
    
    // If quaternions are very close, use linear interpolation
    if (dot > 0.9995f) {
      return Quat(
        a.x + t * (b_adj.x - a.x),
        a.y + t * (b_adj.y - a.y),
        a.z + t * (b_adj.z - a.z),
        a.w + t * (b_adj.w - a.w)
      ).normalized();
    }
    
    float theta_0 = std::acos(dot);
    float theta = theta_0 * t;
    float sin_theta = std::sin(theta);
    float sin_theta_0 = std::sin(theta_0);
    
    float s0 = std::cos(theta) - dot * sin_theta / sin_theta_0;
    float s1 = sin_theta / sin_theta_0;
    
    return Quat(
      s0 * a.x + s1 * b_adj.x,
      s0 * a.y + s1 * b_adj.y,
      s0 * a.z + s1 * b_adj.z,
      s0 * a.w + s1 * b_adj.w
    );
  }

  Quat normalized() const {
    float len = std::sqrt(x * x + y * y + z * z + w * w);
    if (len < 1e-6f) return {0.f, 0.f, 0.f, 1.f};
    float inv = 1.f / len;
    return {x * inv, y * inv, z * inv, w * inv};
  }
};

// Interpolated state for a single entity (ball, player, etc.)
struct InterpolatedState {
  Vec3 position;
  Quat rotation;
  float timestamp = 0.f;  // Time since logic frame (in seconds)
};

//Interpolator: manages interpolation between logic frames
// 
// Usage:
// 1. Call SaveState() after each logic frame to store the current state
// 2. Call GetInterpolatedState() during rendering to get the interpolated state
//    based on time elapsed since last logic frame
//
// The interpolator stores two frames (previous and current) and interpolates
// between them based on the elapsed time.
class Interpolator {
 public:
  Interpolator() = default;

  // Save a new logic frame state
  // timestamp: time in seconds when this logic frame occurred
  void SaveState(float timestamp) {
    // Shift current to previous
    previous_state_ = current_state_;
    previous_timestamp_ = current_timestamp_;
    
    // Store new state
    current_timestamp_ = timestamp;
    states_saved_ = true;
  }

  // Save position for a specific entity index
  void SavePosition(size_t entity_index, const Vec3& position) {
    if (entity_index >= current_state_.size()) {
      current_state_.resize(entity_index + 1);
    }
    current_state_[entity_index].position = position;
  }

  // Save rotation for a specific entity index
  void SaveRotation(size_t entity_index, const Quat& rotation) {
    if (entity_index >= current_state_.size()) {
      current_state_.resize(entity_index + 1);
    }
    current_state_[entity_index].rotation = rotation;
  }

  // Get interpolated state for an entity at a given render time
  // render_time: time in seconds when rendering occurs
  // logic_dt: time between logic frames (e.g., 0.1 seconds for 10 Hz)
  InterpolatedState GetInterpolatedState(size_t entity_index, 
                                         float render_time,
                                         float logic_dt) const {
    InterpolatedState result;
    
    if (!states_saved_ || entity_index >= current_state_.size()) {
      return result;
    }
    
    // Calculate interpolation factor (0 = previous frame, 1 = current frame)
    float elapsed = render_time - current_timestamp_;
    float t = std::clamp(elapsed / logic_dt, 0.f, 1.f);
    
    // If we have a previous frame, interpolate
    if (entity_index < previous_state_.size()) {
      result.position = lerp(previous_state_[entity_index].position,
                            current_state_[entity_index].position, t);
      result.rotation = Quat::slerp(previous_state_[entity_index].rotation,
                                   current_state_[entity_index].rotation, t);
    } else {
      // No previous frame, just use current
      result.position = current_state_[entity_index].position;
      result.rotation = current_state_[entity_index].rotation;
    }
    
    result.timestamp = render_time;
    return result;
  }

  // Check if states have been saved
  bool HasStates() const { return states_saved_; }

  // Get number of entities
  size_t GetEntityCount() const { return current_state_.size(); }

 private:
  // Linear interpolation for vectors
  static Vec3 lerp(const Vec3& a, const Vec3& b, float t) {
    return Vec3(
      a.x + t * (b.x - a.x),
      a.y + t * (b.y - a.y),
      a.z + t * (b.z - a.z)
    );
  }

  std::vector<InterpolatedState> previous_state_;
  std::vector<InterpolatedState> current_state_;
  float previous_timestamp_ = 0.f;
  float current_timestamp_ = 0.f;
  bool states_saved_ = false;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_INTERPOLATOR_HPP
