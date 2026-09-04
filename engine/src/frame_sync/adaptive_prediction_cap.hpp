// Copyright 2026 Google LLC & Contributors
// Adaptive Prediction Cap for frame sync (ms-16.6).
// Dynamically adjusts maximum prediction frames based on network conditions
// and prediction accuracy to balance responsiveness vs. visual artifacts.
//
// Usage:
//   AdaptivePredictionCap cap;
//   cap.UpdateNetworkConditions(rtt_ms, packet_loss);
//   cap.UpdatePredictionAccuracy(accuracy);
//   int max_frames = cap.GetMaxPredictAhead();

#ifndef GFOOTBALL_FRAME_SYNC_ADAPTIVE_PREDICTION_CAP_HPP
#define GFOOTBALL_FRAME_SYNC_ADAPTIVE_PREDICTION_CAP_HPP

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace frame_sync {

/// @brief Adaptive prediction cap
///
/// Adjusts maximum prediction frames based on:
/// - Network RTT (higher RTT → more prediction needed)
/// - Packet loss (higher loss → less prediction, more rollback risk)
/// - Prediction accuracy (low accuracy → reduce prediction)
/// - Frame time stability (unstable frames → reduce prediction)
class AdaptivePredictionCap {
 public:
  /// @brief Get current configuration summary
  struct CapSummary {
    int max_predict_ahead;      ///< Current max prediction frames
    int rtt_component;          ///< RTT-based component
    double packet_loss_penalty; ///< Packet loss adjustment factor
    double accuracy_penalty;    ///< Accuracy adjustment factor
    double stability_penalty;   ///< Frame stability adjustment factor
  };

  /// @brief Recommended extrapolation bounds
  struct ExtrapolationBounds {
    float max_distance;      ///< Maximum extrapolation distance
    float max_speed;         ///< Maximum extrapolation speed
    float max_time;          ///< Maximum extrapolation time
  };

  AdaptivePredictionCap() = default;

  /// @brief Update network conditions
  /// @param rtt_ms Smoothed round-trip time in milliseconds
  /// @param packet_loss Packet loss rate (0.0 - 1.0)
  void UpdateNetworkConditions(double rtt_ms, double packet_loss) {
    rtt_ms_ = rtt_ms;
    packet_loss_ = packet_loss;
  }

  /// @brief Update prediction accuracy
  /// @param accuracy Prediction accuracy (0.0 - 1.0)
  void UpdatePredictionAccuracy(double accuracy) {
    prediction_accuracy_ = accuracy;
  }

  /// @brief Update frame time stability
  /// @param avg_frame_time_ms Average frame time in milliseconds
  /// @param jitter_ms Frame time jitter (standard deviation)
  void UpdateFrameTime(double avg_frame_time_ms, double jitter_ms) {
    avg_frame_time_ms_ = avg_frame_time_ms;
    frame_time_jitter_ms_ = jitter_ms;
  }

  /// @brief Get maximum frames to predict ahead
  /// @return Maximum prediction frames (1-8)
  [[nodiscard]] int GetMaxPredictAhead() const {
    // Start with base value based on RTT
    int max_frames = CalculateRTTBasedCap();
    
    // Adjust for packet loss
    max_frames = AdjustForPacketLoss(max_frames);
    
    // Adjust for prediction accuracy
    max_frames = AdjustForAccuracy(max_frames);
    
    // Adjust for frame time stability
    max_frames = AdjustForFrameStability(max_frames);
    
    // Clamp to valid range
    return std::clamp(max_frames, kMinPredictAhead, kMaxPredictAhead);
  }

  /// @brief Get detailed cap summary
  [[nodiscard]] CapSummary GetSummary() const {
    CapSummary summary;
    summary.max_predict_ahead = GetMaxPredictAhead();
    summary.rtt_component = CalculateRTTBasedCap();
    summary.packet_loss_penalty = CalculatePacketLossPenalty();
    summary.accuracy_penalty = CalculateAccuracyPenalty();
    summary.stability_penalty = CalculateStabilityPenalty();
    return summary;
  }

  /// @brief Get recommended extrapolation bounds
  [[nodiscard]] ExtrapolationBounds GetRecommendedBounds() const {
    ExtrapolationBounds bounds;
    
    int max_frames = GetMaxPredictAhead();
    float logic_dt = 0.1f;  // Standard 10Hz logic
    
    bounds.max_time = max_frames * logic_dt;
    bounds.max_speed = CalculateMaxSpeed();
    bounds.max_distance = bounds.max_speed * bounds.max_time;
    
    return bounds;
  }

  /// @brief Reset to defaults
  void Reset() {
    rtt_ms_ = 0.0;
    packet_loss_ = 0.0;
    prediction_accuracy_ = 1.0;
    avg_frame_time_ms_ = 16.67;
    frame_time_jitter_ms_ = 0.0;
  }

 private:
  static constexpr int kMinPredictAhead = 1;
  static constexpr int kMaxPredictAhead = 8;
  static constexpr int kBasePredictAhead = 3;

  /// @brief Calculate RTT-based prediction cap
  [[nodiscard]] int CalculateRTTBasedCap() const {
    // Higher RTT → more prediction needed to hide latency
    if (rtt_ms_ < 30.0) return 1;
    if (rtt_ms_ < 50.0) return 2;
    if (rtt_ms_ < 80.0) return 3;
    if (rtt_ms_ < 120.0) return 4;
    if (rtt_ms_ < 180.0) return 5;
    return 6;
  }

  /// @brief Calculate packet loss penalty factor
  [[nodiscard]] double CalculatePacketLossPenalty() const {
    // High packet loss → reduce prediction (more rollbacks)
    if (packet_loss_ < 0.01) return 1.0;
    if (packet_loss_ < 0.03) return 0.9;
    if (packet_loss_ < 0.05) return 0.8;
    if (packet_loss_ < 0.10) return 0.6;
    return 0.4;
  }

  /// @brief Calculate accuracy penalty factor
  [[nodiscard]] double CalculateAccuracyPenalty() const {
    // Low accuracy → reduce prediction
    if (prediction_accuracy_ > 0.95) return 1.0;
    if (prediction_accuracy_ > 0.90) return 0.9;
    if (prediction_accuracy_ > 0.80) return 0.8;
    if (prediction_accuracy_ > 0.70) return 0.6;
    return 0.4;
  }

  /// @brief Calculate frame stability penalty factor
  [[nodiscard]] double CalculateStabilityPenalty() const {
    // High jitter → reduce prediction
    if (frame_time_jitter_ms_ < 1.0) return 1.0;
    if (frame_time_jitter_ms_ < 2.0) return 0.9;
    if (frame_time_jitter_ms_ < 4.0) return 0.8;
    if (frame_time_jitter_ms_ < 8.0) return 0.6;
    return 0.4;
  }

  /// @brief Adjust cap for packet loss
  [[nodiscard]] int AdjustForPacketLoss(int base_cap) const {
    double penalty = CalculatePacketLossPenalty();
    return static_cast<int>(std::round(base_cap * penalty));
  }

  /// @brief Adjust cap for accuracy
  [[nodiscard]] int AdjustForAccuracy(int base_cap) const {
    double penalty = CalculateAccuracyPenalty();
    return static_cast<int>(std::round(base_cap * penalty));
  }

  /// @brief Adjust cap for frame stability
  [[nodiscard]] int AdjustForFrameStability(int base_cap) const {
    double penalty = CalculateStabilityPenalty();
    return static_cast<int>(std::round(base_cap * penalty));
  }

  /// @brief Calculate maximum allowed extrapolation speed
  [[nodiscard]] float CalculateMaxSpeed() const {
    // Base speed (m/s) - typical football player speed
    float base_speed = 10.0f;
    
    // Reduce speed limit when accuracy is low
    if (prediction_accuracy_ < 0.8) {
      base_speed *= 0.7f;
    } else if (prediction_accuracy_ < 0.9) {
      base_speed *= 0.85f;
    }
    
    return base_speed;
  }

  double rtt_ms_ = 0.0;
  double packet_loss_ = 0.0;
  double prediction_accuracy_ = 1.0;
  double avg_frame_time_ms_ = 16.67;
  double frame_time_jitter_ms_ = 0.0;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_ADAPTIVE_PREDICTION_CAP_HPP
