// Copyright 2026 Google LLC & Contributors
// Frame interpolation for logic-render separation (ms-1.6).
// Provides temporal interpolation between logic frames for smooth rendering.
//
// This module provides interpolation utilities for smooth rendering when
// the logic frame rate differs from the render frame rate. It includes:
//   - Vec3: Simple 3D vector with arithmetic operations
//   - Quat: Quaternion with spherical linear interpolation (slerp)
//   - Interpolator: Manages interpolation between logic frames
//
// Usage:
//   Interpolator interp;
//   // After each logic frame:
//   interp.SaveState(logic_timestamp);
//   interp.SavePosition(entity_index, position);
//   // During rendering:
//   auto state = interp.GetInterpolatedState(entity_index, render_time, logic_dt);

#ifndef GFOOTBALL_FRAME_SYNC_INTERPOLATOR_HPP
#define GFOOTBALL_FRAME_SYNC_INTERPOLATOR_HPP

#include <chrono>
#include <cmath>
#include <cstdint>
#include <functional>
#include <vector>

namespace frame_sync {

/// @brief Simple 3D vector for interpolation
struct Vec3 {
  float x = 0.f;  ///< X component
  float y = 0.f;  ///< Y component
  float z = 0.f;  ///< Z component

  Vec3() = default;
  Vec3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}

  Vec3 operator+(const Vec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
  Vec3 operator-(const Vec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
  Vec3 operator*(float s) const { return {x * s, y * s, z * s}; }

  /// @brief Calculate squared length (avoids square root)
  [[nodiscard]] float length_sq() const { return x * x + y * y + z * z; }
  
  /// @brief Calculate vector length
  [[nodiscard]] float length() const { return std::sqrt(length_sq()); }

  /// @brief Get normalized vector (unit length)
  [[nodiscard]] Vec3 normalized() const {
    float len = length();
    if (len < 1e-6f) return {0.f, 0.f, 0.f};
    return *this * (1.f / len);
  }
};

/// @brief Simple quaternion for rotation interpolation
struct Quat {
  float x = 0.f;  ///< X component
  float y = 0.f;  ///< Y component
  float z = 0.f;  ///< Z component
  float w = 1.f;  ///< W component (real part)

  Quat() = default;
  Quat(float x_, float y_, float z_, float w_) : x(x_), y(y_), z(z_), w(w_) {}

  /// @brief Spherical linear interpolation between two quaternions
  /// @param a Start quaternion
  /// @param b End quaternion
  /// @param t Interpolation factor (0 = a, 1 = b)
  /// @return Interpolated quaternion
  [[nodiscard]] static Quat slerp(const Quat& a, const Quat& b, float t) {
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

  /// @brief Get normalized quaternion (unit length)
  [[nodiscard]] Quat normalized() const {
    float len = std::sqrt(x * x + y * y + z * z + w * w);
    if (len < 1e-6f) return {0.f, 0.f, 0.f, 1.f};
    float inv = 1.f / len;
    return {x * inv, y * inv, z * inv, w * inv};
  }
};

/// @brief Interpolated state for a single entity (ball, player, etc.)
struct InterpolatedState {
  Vec3 position;           ///< Interpolated position
  Quat rotation;           ///< Interpolated rotation
  float timestamp = 0.f;   ///< Time since logic frame (in seconds)
};

/// @brief Interpolator: manages interpolation between logic frames
/// 
/// Usage:
/// 1. Call SaveState() after each logic frame to store the current state
/// 2. Call GetInterpolatedState() during rendering to get the interpolated state
///    based on time elapsed since last logic frame
///
/// The interpolator stores two frames (previous and current) and interpolates
/// between them based on the elapsed time.
class Interpolator {
 public:
  Interpolator() = default;

  /// @brief Save a new logic frame state
  /// @param timestamp Time in seconds when this logic frame occurred
  void SaveState(float timestamp) {
    // Shift current to previous
    previous_state_ = current_state_;
    previous_timestamp_ = current_timestamp_;
    
    // Store new state
    current_timestamp_ = timestamp;
    states_saved_ = true;
  }

  /// @brief Save position for a specific entity index
  /// @param entity_index Index of the entity (0-based)
  /// @param position Position to save
  void SavePosition(size_t entity_index, const Vec3& position) {
    if (entity_index >= current_state_.size()) {
      current_state_.resize(entity_index + 1);
    }
    current_state_[entity_index].position = position;
  }

  /// @brief Save rotation for a specific entity index
  /// @param entity_index Index of the entity (0-based)
  /// @param rotation Rotation to save
  void SaveRotation(size_t entity_index, const Quat& rotation) {
    if (entity_index >= current_state_.size()) {
      current_state_.resize(entity_index + 1);
    }
    current_state_[entity_index].rotation = rotation;
  }

  /// @brief Get interpolated state for an entity at a given render time
  /// @param entity_index Index of the entity (0-based)
  /// @param render_time Time in seconds when rendering occurs
  /// @param logic_dt Time between logic frames (e.g., 0.1 seconds for 10 Hz)
  /// @return Interpolated state for the entity
  [[nodiscard]] InterpolatedState GetInterpolatedState(size_t entity_index, 
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
