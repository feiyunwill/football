// Copyright 2026 Google LLC & Contributors
// Latency Compensation for frame sync (ms-17.1).
// Adjusts input timing based on measured RTT to reduce perceived latency.
//
// Usage:
//   LatencyCompensator comp;
//   comp.RecordRoundTrip(local_time_ms, server_time_ms);
//   int64_t adjusted_offset = comp.GetAdjustedOffset();
//   comp.AdjustInputTiming(input, adjusted_offset);

#ifndef GFOOTBALL_FRAME_SYNC_LATENCY_COMPENSATOR_HPP
#define GFOOTBALL_FRAME_SYNC_LATENCY_COMPENSATOR_HPP

#include <cstdint>
#include <deque>
#include <algorithm>
#include <cmath>

namespace frame_sync {

/// @brief Latency compensator
///
/// Measures round-trip time and provides adjusted timing offsets
/// to compensate for network latency. Uses a sliding window
/// for stable RTT estimation.
class LatencyCompensator {
 public:
  LatencyCompensator() = default;

  /// @brief Record a round-trip measurement
  /// @param send_time_ms Local time when request was sent
  /// @param server_time_ms Server time when request was received (from heartbeat)
  /// @param recv_time_ms Local time when response was received
  void RecordRoundTrip(double send_time_ms, double server_time_ms, double recv_time_ms) {
    double rtt = recv_time_ms - send_time_ms;
    if (rtt < 0) return;  // Invalid measurement
    
    rtt_samples_.push_back(rtt);
    if (rtt_samples_.size() > kMaxSamples) {
      rtt_samples_.pop_front();
    }
    
    // Estimate one-way latency (half RTT with jitter compensation)
    double estimated_oneway = rtt / 2.0;
    oneway_estimates_.push_back(estimated_oneway);
    if (oneway_estimates_.size() > kMaxSamples) {
      oneway_estimates_.pop_front();
    }
  }

  /// @brief Record a simple RTT measurement (no server timestamp)
  /// @param send_time_ms Local time when request was sent
  /// @param recv_time_ms Local time when response was received
  void RecordRTT(double send_time_ms, double recv_time_ms) {
    double rtt = recv_time_ms - send_time_ms;
    if (rtt < 0) return;
    
    rtt_samples_.push_back(rtt);
    if (rtt_samples_.size() > kMaxSamples) {
      rtt_samples_.pop_front();
    }
    
    double estimated_oneway = rtt / 2.0;
    oneway_estimates_.push_back(estimated_oneway);
    if (oneway_estimates_.size() > kMaxSamples) {
      oneway_estimates_.pop_front();
    }
  }

  /// @brief Get smoothed RTT estimate
  [[nodiscard]] double GetSmoothedRTT() const {
    if (rtt_samples_.empty()) return 0.0;
    
    // Use weighted average (recent samples weighted more)
    double sum = 0.0;
    double weight_sum = 0.0;
    double weight = 1.0;
    
    for (auto it = rtt_samples_.rbegin(); it != rtt_samples_.rend(); ++it) {
      sum += (*it) * weight;
      weight_sum += weight;
      weight *= 0.9;  // Exponential decay
    }
    
    return sum / weight_sum;
  }

  /// @brief Get one-way latency estimate
  [[nodiscard]] double GetEstimatedOneWay() const {
    if (oneway_estimates_.empty()) return 0.0;
    return oneway_estimates_.back();
  }

  /// @brief Get adjusted time offset for input compensation
  /// @return Milliseconds to add to local time for server-aligned time
  [[nodiscard]] double GetAdjustedOffset() const {
    // Offset = one-way latency + jitter compensation
    double oneway = GetEstimatedOneWay();
    double jitter = GetJitter();
    
    // Add half jitter as safety margin
    return oneway + jitter * 0.5;
  }

  /// @brief Get jitter (standard deviation of RTT)
  [[nodiscard]] double GetJitter() const {
    if (rtt_samples_.size() < 2) return 0.0;
    
    double mean = GetSmoothedRTT();
    double sum_sq = 0.0;
    for (double v : rtt_samples_) {
      double diff = v - mean;
      sum_sq += diff * diff;
    }
    return std::sqrt(sum_sq / rtt_samples_.size());
  }

  /// @brief Get minimum observed RTT
  [[nodiscard]] double GetMinRTT() const {
    if (rtt_samples_.empty()) return 0.0;
    return *std::min_element(rtt_samples_.begin(), rtt_samples_.end());
  }

  /// @brief Get maximum observed RTT
  [[nodiscard]] double GetMaxRTT() const {
    if (rtt_samples_.empty()) return 0.0;
    return *std::max_element(rtt_samples_.begin(), rtt_samples_.end());
  }

  /// @brief Get compensation status
  struct CompensationStatus {
    double smoothed_rtt_ms;    ///< Smoothed RTT
    double estimated_oneway_ms; ///< One-way latency estimate
    double jitter_ms;          ///< Jitter (std dev)
    double adjusted_offset_ms; ///< Total compensation offset
    double min_rtt_ms;         ///< Minimum RTT
    double max_rtt_ms;         ///< Maximum RTT
    size_t sample_count;       ///< Number of RTT samples
  };

  /// @brief Get detailed compensation status
  [[nodiscard]] CompensationStatus GetStatus() const {
    return {
      GetSmoothedRTT(),
      GetEstimatedOneWay(),
      GetJitter(),
      GetAdjustedOffset(),
      GetMinRTT(),
      GetMaxRTT(),
      rtt_samples_.size()
    };
  }

  /// @brief Check if compensation is active (enough samples)
  [[nodiscard]] bool IsActive() const {
    return rtt_samples_.size() >= kMinSamplesForCompensation;
  }

  /// @brief Reset all measurements
  void Reset() {
    rtt_samples_.clear();
    oneway_estimates_.clear();
  }

 private:
  static constexpr size_t kMaxSamples = 50;
  static constexpr size_t kMinSamplesForCompensation = 5;

  std::deque<double> rtt_samples_;
  std::deque<double> oneway_estimates_;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_LATENCY_COMPENSATOR_HPP
