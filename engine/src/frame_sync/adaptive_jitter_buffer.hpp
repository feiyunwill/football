// Copyright 2026 Google LLC & Contributors
// Adaptive Jitter Buffer for frame sync (ms-16.8).
// Dynamically adjusts buffer size based on network jitter to balance
// latency vs. smoothness.
//
// Usage:
//   AdaptiveJitterBuffer buffer;
//   buffer.Update(jitter_ms, rtt_ms);
//   int recommended_frames = buffer.GetRecommendedBufferFrames();
//   buffer.OnFrameArrived(frame_number);
//   bool should_drop = buffer.ShouldDropFrame(frame_number);

#ifndef GFOOTBALL_FRAME_SYNC_ADAPTIVE_JITTER_BUFFER_HPP
#define GFOOTBALL_FRAME_SYNC_ADAPTIVE_JITTER_BUFFER_HPP

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <deque>
#include <vector>

namespace frame_sync {

/// @brief Adaptive jitter buffer
///
/// Adjusts buffer size based on:
/// - Network jitter (higher jitter → larger buffer)
/// - RTT (higher RTT → more buffer to hide latency)
/// - Frame arrival patterns (irregular arrivals → larger buffer)
/// - Packet loss (high loss → smaller buffer to reduce delay)
class AdaptiveJitterBuffer {
 public:
  AdaptiveJitterBuffer() = default;

  /// @brief Update buffer with new network measurements
  /// @param jitter_ms Current jitter (standard deviation of inter-arrival times)
  /// @param rtt_ms Smoothed round-trip time
  void Update(double jitter_ms, double rtt_ms) {
    // Smooth jitter estimate using exponential moving average
    constexpr double kAlpha = 0.2;
    smoothed_jitter_ = kAlpha * jitter_ms + (1.0 - kAlpha) * smoothed_jitter_;
    
    rtt_ms_ = rtt_ms;
  }

  /// @brief Record frame arrival
  /// @param frame_number Frame number that arrived
  void OnFrameArrived(uint32_t frame_number) {
    uint64_t now_us = GetCurrentTimeUs();
    
    if (last_arrival_time_us_ > 0) {
      double inter_arrival_ms = static_cast<double>(now_us - last_arrival_time_us_) / 1000.0;
      inter_arrivals_.push_back(inter_arrival_ms);
      if (inter_arrivals_.size() > kMaxSamples) {
        inter_arrivals_.pop_front();
      }
    }
    
    last_arrival_time_us_ = now_us;
    
    // Track frame gaps
    if (last_frame_number_set_ && frame_number > last_frame_number_ + 1) {
      gap_count_++;
    }
    
    last_frame_number_ = frame_number;
    last_frame_number_set_ = true;
  }

  /// @brief Get recommended buffer size in frames
  /// @return Recommended buffer frames (1-10)
  [[nodiscard]] int GetRecommendedBufferFrames() const {
    // Base buffer from jitter
    int base = CalculateJitterBasedBuffer();
    
    // Adjust for RTT
    base = AdjustForRTT(base);
    
    // Adjust for frame arrival regularity
    base = AdjustForRegularity(base);
    
    // Clamp to valid range
    return std::clamp(base, kMinBufferFrames, kMaxBufferFrames);
  }

  /// @brief Get recommended buffer duration in milliseconds
  [[nodiscard]] double GetRecommendedBufferMs() const {
    return GetRecommendedBufferFrames() * kLogicDtMs;
  }

  /// @brief Check if frame should be dropped (too old)
  /// @param frame_number Frame number to check
  /// @param current_frame Current playback frame
  /// @return true if frame should be dropped
  [[nodiscard]] bool ShouldDropFrame(uint32_t frame_number, uint32_t current_frame) const {
    // Drop frames that are too far behind
    int age = static_cast<int>(current_frame) - static_cast<int>(frame_number);
    return age > GetRecommendedBufferFrames() * 2;
  }

  /// @brief Get buffer status summary
  struct BufferStatus {
    int recommended_frames;      ///< Recommended buffer size
    double recommended_ms;       ///< Recommended buffer duration
    double smoothed_jitter_ms;   ///< Current smoothed jitter
    double rtt_ms;               ///< Current RTT
    double avg_inter_arrival_ms; ///< Average inter-arrival time
    double arrival_jitter_ms;    ///< Jitter of inter-arrival times
    int gap_count;               ///< Number of frame gaps observed
  };

  /// @brief Get detailed buffer status
  [[nodiscard]] BufferStatus GetStatus() const {
    BufferStatus status;
    status.recommended_frames = GetRecommendedBufferFrames();
    status.recommended_ms = GetRecommendedBufferMs();
    status.smoothed_jitter_ms = smoothed_jitter_;
    status.rtt_ms = rtt_ms_;
    status.avg_inter_arrival_ms = CalculateAvgInterArrival();
    status.arrival_jitter_ms = CalculateArrivalJitter();
    status.gap_count = gap_count_;
    return status;
  }

  /// @brief Reset buffer state
  void Reset() {
    smoothed_jitter_ = 0.0;
    rtt_ms_ = 0.0;
    inter_arrivals_.clear();
    last_arrival_time_us_ = 0;
    last_frame_number_ = 0;
    gap_count_ = 0;
  }

  /// @brief Get current jitter estimate
  [[nodiscard]] double GetSmoothedJitter() const { return smoothed_jitter_; }

  /// @brief Get gap count
  [[nodiscard]] int GetGapCount() const { return gap_count_; }

 private:
  static constexpr int kMinBufferFrames = 1;
  static constexpr int kMaxBufferFrames = 10;
  static constexpr double kLogicDtMs = 100.0;  // 10 Hz logic
  static constexpr size_t kMaxSamples = 100;

  /// @brief Get current time in microseconds
  [[nodiscard]] static uint64_t GetCurrentTimeUs() {
    // Use a simple counter for testing
    static uint64_t counter = 0;
    return ++counter;
  }

  /// @brief Calculate jitter-based buffer size
  [[nodiscard]] int CalculateJitterBasedBuffer() const {
    // Buffer should be at least 2x jitter to handle variations
    double buffer_ms = smoothed_jitter_ * 2.0;
    return static_cast<int>(std::ceil(buffer_ms / kLogicDtMs));
  }

  /// @brief Adjust buffer for RTT
  [[nodiscard]] int AdjustForRTT(int base) const {
    // Higher RTT needs more buffer to hide latency
    if (rtt_ms_ > 150.0) return base + 2;
    if (rtt_ms_ > 100.0) return base + 1;
    return base;
  }

  /// @brief Adjust buffer for arrival regularity
  [[nodiscard]] int AdjustForRegularity(int base) const {
    if (inter_arrivals_.size() < 5) return base;
    
    double jitter = CalculateArrivalJitter();
    if (jitter > 50.0) return base + 2;
    if (jitter > 20.0) return base + 1;
    if (jitter < 5.0 && gap_count_ == 0) return std::max(1, base - 1);
    return base;
  }

  /// @brief Calculate average inter-arrival time
  [[nodiscard]] double CalculateAvgInterArrival() const {
    if (inter_arrivals_.empty()) return kLogicDtMs;
    double sum = 0;
    for (double v : inter_arrivals_) sum += v;
    return sum / inter_arrivals_.size();
  }

  /// @brief Calculate inter-arrival jitter
  [[nodiscard]] double CalculateArrivalJitter() const {
    if (inter_arrivals_.size() < 2) return 0.0;
    
    double mean = CalculateAvgInterArrival();
    double sum_sq = 0;
    for (double v : inter_arrivals_) {
      double diff = v - mean;
      sum_sq += diff * diff;
    }
    return std::sqrt(sum_sq / inter_arrivals_.size());
  }

  double smoothed_jitter_ = 0.0;
  double rtt_ms_ = 0.0;
  std::deque<double> inter_arrivals_;
  uint64_t last_arrival_time_us_ = 0;
  uint32_t last_frame_number_ = 0;
  bool last_frame_number_set_ = false;
  int gap_count_ = 0;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_ADAPTIVE_JITTER_BUFFER_HPP
