// Copyright 2026 Google LLC & Contributors
// UX optimization: input latency tracking, render smoothness, adaptive quality.
//
// This module provides tools for monitoring and optimizing user experience
// in the frame sync system. It tracks input latency, frame render times,
// network quality, and prediction accuracy to provide adaptive quality
// recommendations.
//
// Usage:
//   UXOptimizer optimizer;
//   optimizer.RecordInputLatency(50.0);
//   optimizer.RecordFrameTime(16.67);
//   auto stats = optimizer.GetStats();
//   auto rec = optimizer.GetQualityRecommendation();
//
// Key classes:
//   - UXOptimizer: Main optimizer for tracking and recommendations
//   - InputLatencyTracker: Precise input latency measurement
//   - UXStats: Statistics snapshot
//   - QualityRecommendation: Adaptive quality settings

#ifndef GFOOTBALL_FRAME_SYNC_UX_OPTIMIZER_HPP
#define GFOOTBALL_FRAME_SYNC_UX_OPTIMIZER_HPP

#include "frame_sync/protocol.hpp"
#include <chrono>
#include <deque>
#include <cmath>
#include <cstdint>
#include <algorithm>
#include <unordered_map>

namespace frame_sync {

/// @brief Network quality levels based on RTT and packet loss
enum class NetworkQuality : std::uint8_t {
  kExcellent,  ///< RTT < 50ms, no packet loss
  kGood,       ///< RTT < 100ms, < 1% loss
  kFair,       ///< RTT < 150ms, < 3% loss
  kPoor,       ///< RTT < 200ms, < 5% loss
  kBad         ///< RTT >= 200ms or >= 5% loss
};

/// @brief Statistics snapshot for UX monitoring
struct UXStats {
  // Input latency
  double avg_input_latency_ms = 0.0;    ///< Average input latency in milliseconds
  double max_input_latency_ms = 0.0;    ///< Maximum input latency observed
  double p95_input_latency_ms = 0.0;    ///< 95th percentile input latency
  
  // Render smoothness
  double avg_frame_time_ms = 0.0;       ///< Average frame render time in milliseconds
  double frame_time_jitter_ms = 0.0;    ///< Standard deviation of frame times
  double fps = 0.0;                     ///< Estimated frames per second
  
  // Network quality
  NetworkQuality network_quality = NetworkQuality::kGood;  ///< Current network quality level
  double smoothed_rtt_ms = 0.0;         ///< Smoothed round-trip time
  double packet_loss_rate = 0.0;        ///< Current packet loss rate (0.0 - 1.0)
  
  // Prediction accuracy
  double prediction_accuracy = 0.0;     ///< Ratio of correct predictions (0.0 - 1.0)
  int rollback_count = 0;               ///< Number of rollbacks performed
  int total_frames = 0;                 ///< Total frames processed
};

/// @brief UX Optimizer: monitors and optimizes user experience
///
/// This class tracks various UX metrics and provides adaptive quality
/// recommendations based on network conditions and performance.
class UXOptimizer {
 public:
  UXOptimizer() = default;
  
  /// @brief Record input latency measurement
  /// @param latency_ms Time from input generation to authoritative confirmation (ms)
  void RecordInputLatency(double latency_ms) {
    input_latencies_.push_back(latency_ms);
    if (input_latencies_.size() > kMaxSamples) {
      input_latencies_.pop_front();
    }
    
    total_input_latency_ += latency_ms;
    input_latency_count_++;
  }
  
  /// @brief Record frame render time
  /// @param frame_time_ms Time to render a frame (ms)
  void RecordFrameTime(double frame_time_ms) {
    frame_times_.push_back(frame_time_ms);
    if (frame_times_.size() > kMaxSamples) {
      frame_times_.pop_front();
    }
    
    total_frame_time_ += frame_time_ms;
    frame_time_count_++;
  }
  
  /// @brief Record packet loss rate
  /// @param loss_rate Packet loss ratio (0.0 = no loss, 1.0 = 100% loss)
  void RecordPacketLoss(double loss_rate) {
    packet_losses_.push_back(loss_rate);
    if (packet_losses_.size() > kMaxSamples) {
      packet_losses_.pop_front();
    }
  }
  
  /// @brief Record prediction result
  /// @param correct True if prediction matched authoritative state
  void RecordPrediction(bool correct) {
    predictions_.push_back(correct);
    if (predictions_.size() > kMaxSamples) {
      predictions_.pop_front();
    }
  }
  
  /// @brief Get current UX statistics
  /// @return Snapshot of current UX metrics
  [[nodiscard]] UXStats GetStats() const {
    UXStats stats;
    
    // Input latency stats
    if (!input_latencies_.empty()) {
      double sum = 0;
      double max_val = 0;
      for (double v : input_latencies_) {
        sum += v;
        max_val = std::max(max_val, v);
      }
      stats.avg_input_latency_ms = sum / input_latencies_.size();
      stats.max_input_latency_ms = max_val;
      
      // Calculate P95
      std::vector<double> sorted_latencies(input_latencies_.begin(), input_latencies_.end());
      std::sort(sorted_latencies.begin(), sorted_latencies.end());
      size_t p95_index = static_cast<size_t>(sorted_latencies.size() * 0.95);
      stats.p95_input_latency_ms = sorted_latencies[p95_index];
    }
    
    // Frame time stats
    if (!frame_times_.empty()) {
      double sum = 0;
      for (double v : frame_times_) {
        sum += v;
      }
      stats.avg_frame_time_ms = sum / frame_times_.size();
      stats.fps = 1000.0 / stats.avg_frame_time_ms;
      
      // Calculate jitter (std dev)
      double sum_sq = 0;
      for (double v : frame_times_) {
        double diff = v - stats.avg_frame_time_ms;
        sum_sq += diff * diff;
      }
      stats.frame_time_jitter_ms = std::sqrt(sum_sq / frame_times_.size());
    }
    
    // Network quality
    stats.network_quality = CalculateNetworkQuality();
    stats.smoothed_rtt_ms = CalculateSmoothedRTT();
    stats.packet_loss_rate = CalculatePacketLossRate();
    
    // Prediction accuracy
    if (!predictions_.empty()) {
      int correct = 0;
      for (bool v : predictions_) {
        if (v) correct++;
      }
      stats.prediction_accuracy = static_cast<double>(correct) / predictions_.size();
    }
    
    stats.rollback_count = rollback_count_;
    stats.total_frames = input_latency_count_;
    
    return stats;
  }
  
  /// @brief Increment rollback counter
  void IncrementRollbackCount() {
    rollback_count_++;
  }
  
  /// @brief Reset all statistics to initial state
  void Reset() {
    input_latencies_.clear();
    frame_times_.clear();
    packet_losses_.clear();
    predictions_.clear();
    total_input_latency_ = 0;
    input_latency_count_ = 0;
    total_frame_time_ = 0;
    frame_time_count_ = 0;
    rollback_count_ = 0;
  }
  
  /// @brief Adaptive quality recommendation based on current metrics
  struct QualityRecommendation {
    bool reduce_render_quality = false;    ///< Reduce rendering quality (e.g., lower resolution)
    bool reduce_network_frequency = false; ///< Reduce network update frequency
    bool increase_prediction = false;      ///< Increase prediction window
    int max_predict_ahead = 3;            ///< Maximum frames to predict ahead
    float render_scale = 1.0f;            ///< Render resolution scale (0.5 - 1.0)
  };
  
  /// @brief Get adaptive quality recommendation based on current metrics
  /// @return QualityRecommendation with suggested settings
  [[nodiscard]] QualityRecommendation GetQualityRecommendation() const {
    QualityRecommendation rec;
    auto stats = GetStats();
    
    // Based on network quality
    if (stats.network_quality == NetworkQuality::kPoor) {
      rec.reduce_network_frequency = true;
      rec.increase_prediction = true;
      rec.max_predict_ahead = 4;
      rec.render_scale = 0.75f;
    } else if (stats.network_quality == NetworkQuality::kBad) {
      rec.reduce_network_frequency = true;
      rec.increase_prediction = true;
      rec.max_predict_ahead = 5;
      rec.render_scale = 0.5f;
    }
    
    // Based on frame time
    if (stats.avg_frame_time_ms > 20.0) {  // Below 50 FPS
      rec.reduce_render_quality = true;
      rec.render_scale = std::max(0.5f, rec.render_scale);
    }
    
    // Based on input latency
    if (stats.p95_input_latency_ms > 150.0) {
      rec.increase_prediction = true;
      rec.max_predict_ahead = std::max(rec.max_predict_ahead, 4);
    }
    
    return rec;
  }
  
 private:
  static constexpr size_t kMaxSamples = 100;
  
  NetworkQuality CalculateNetworkQuality() const {
    double rtt = CalculateSmoothedRTT();
    double loss = CalculatePacketLossRate();
    
    if (rtt < 50.0 && loss < 0.01) return NetworkQuality::kExcellent;
    if (rtt < 100.0 && loss < 0.01) return NetworkQuality::kGood;
    if (rtt < 150.0 && loss < 0.03) return NetworkQuality::kFair;
    if (rtt < 200.0 && loss < 0.05) return NetworkQuality::kPoor;
    return NetworkQuality::kBad;
  }
  
  [[nodiscard]] double CalculateSmoothedRTT() const {
    if (input_latencies_.empty()) return 0.0;
    
    // Simple moving average
    double sum = 0;
    for (double v : input_latencies_) {
      sum += v;
    }
    return sum / input_latencies_.size();
  }
  
  [[nodiscard]] double CalculatePacketLossRate() const {
    if (packet_losses_.empty()) return 0.0;
    
    double sum = 0;
    for (double v : packet_losses_) {
      sum += v;
    }
    return sum / packet_losses_.size();
  }
  
  std::deque<double> input_latencies_;
  std::deque<double> frame_times_;
  std::deque<double> packet_losses_;
  std::deque<bool> predictions_;
  
  double total_input_latency_ = 0;
  size_t input_latency_count_ = 0;
  double total_frame_time_ = 0;
  size_t frame_time_count_ = 0;
  int rollback_count_ = 0;
};

/// @brief Precise input latency tracker for frame-level measurements
///
/// This class tracks input latency by recording when inputs are generated
/// and when they are confirmed by authoritative frames. It provides
/// statistical analysis including average and P95 latency.
///
/// Usage:
///   InputLatencyTracker tracker;
///   tracker.RecordInputTime(frame_id, std::chrono::steady_clock::now());
///   // ... later when authoritative frame arrives ...
///   tracker.RecordConfirmation(frame_id, std::chrono::steady_clock::now());
///   double avg_latency = tracker.GetAverageLatencyMs();
class InputLatencyTracker {
 public:
  InputLatencyTracker() = default;
  
  /// @brief Record when input was generated
  /// @param frame_id Frame ID of the input
  /// @param time Timestamp when input was created
  void RecordInputTime(frame_id_t frame_id, std::chrono::steady_clock::time_point time) {
    input_times_[frame_id] = time;
  }
  
  /// @brief Record when input was confirmed (authoritative frame received)
  /// @param frame_id Frame ID of the input
  /// @param time Timestamp when authoritative frame was received
  void RecordConfirmation(frame_id_t frame_id, std::chrono::steady_clock::time_point time) {
    auto it = input_times_.find(frame_id);
    if (it != input_times_.end()) {
      auto latency = std::chrono::duration_cast<std::chrono::milliseconds>(time - it->second);
      latencies_.push_back(latency.count());
      if (latencies_.size() > kMaxSamples) {
        latencies_.pop_front();
      }
      input_times_.erase(it);
    }
  }
  
  /// @brief Get average latency in milliseconds
  [[nodiscard]] double GetAverageLatencyMs() const {
    if (latencies_.empty()) return 0.0;
    double sum = 0;
    for (double v : latencies_) {
      sum += v;
    }
    return sum / latencies_.size();
  }
  
  /// @brief Get 95th percentile latency in milliseconds
  [[nodiscard]] double GetP95LatencyMs() const {
    if (latencies_.empty()) return 0.0;
    std::vector<double> sorted(latencies_.begin(), latencies_.end());
    std::sort(sorted.begin(), sorted.end());
    size_t index = static_cast<size_t>(sorted.size() * 0.95);
    return sorted[index];
  }
  
  /// @brief Remove old entries to prevent memory growth
  /// @param current_frame Current frame ID
  /// @param max_age_frames Maximum age in frames to keep
  void Cleanup(frame_id_t current_frame, int max_age_frames = 100) {
    for (auto it = input_times_.begin(); it != input_times_.end(); ) {
      if (it->first < current_frame - max_age_frames) {
        it = input_times_.erase(it);
      } else {
        ++it;
      }
    }
  }
  
 private:
  static constexpr size_t kMaxSamples = 100;
  std::unordered_map<frame_id_t, std::chrono::steady_clock::time_point> input_times_;
  std::deque<double> latencies_;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_UX_OPTIMIZER_HPP
