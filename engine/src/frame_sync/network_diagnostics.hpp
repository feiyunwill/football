// Copyright 2026 Google LLC & Contributors
// Network diagnostics for frame sync (ms-17.5).
// Aggregates RTT, jitter, packet loss, prediction accuracy, and quality rating.
//
// Usage:
//   NetworkDiagnostics diag;
//   diag.Update(rtt, jitter, accuracy, frames_without_packet, total_frames);
//   auto report = diag.GetReport();
//   std::string overlay = diag.FormatOverlay();

#ifndef GFOOTBALL_FRAME_SYNC_NETWORK_DIAGNOSTICS_HPP
#define GFOOTBALL_FRAME_SYNC_NETWORK_DIAGNOSTICS_HPP

#include <cstdint>
#include <string>
#include <deque>
#include <algorithm>
#include <cmath>
#include <chrono>

namespace frame_sync {

/// @brief Network quality rating
enum class NetworkQuality : uint8_t {
  kExcellent,  // RTT < 50ms, jitter < 5ms
  kGood,       // RTT < 100ms, jitter < 15ms
  kFair,       // RTT < 200ms, jitter < 30ms
  kPoor,       // RTT >= 200ms or jitter >= 30ms
  kCritical,   // RTT >= 500ms or packet loss > 10%
};

/// @brief Diagnostic report
struct DiagnosticReport {
  double smoothed_rtt_ms = 0.0;       ///< Smoothed RTT in milliseconds
  double jitter_ms = 0.0;             ///< Jitter (std dev) in milliseconds
  double packet_loss_pct = 0.0;       ///< Packet loss percentage
  double prediction_accuracy = 1.0;   ///< Prediction accuracy (0-1)
  int frames_without_packet = 0;      ///< Consecutive frames without server packet
  int total_frames = 0;               ///< Total frames processed
  int rollback_count = 0;             ///< Total rollbacks
  NetworkQuality quality = NetworkQuality::kExcellent;
  std::string quality_str;            ///< Human-readable quality
  std::string overlay_text;           ///< Full overlay text for display
};

/// @brief Network diagnostics aggregator
class NetworkDiagnostics {
 public:
  NetworkDiagnostics() = default;

  /// @brief Update with latest network conditions
  void Update(double rtt_ms, double jitter_ms, double prediction_accuracy,
              int frames_without_packet, int rollback_count, int total_frames) {
    rtt_samples_.push_back(rtt_ms);
    if (rtt_samples_.size() > kMaxSamples) rtt_samples_.pop_front();

    smoothed_rtt_ = SmoothedValue(rtt_samples_);
    jitter_ = jitter_ms;
    prediction_accuracy_ = prediction_accuracy;
    frames_without_packet_ = frames_without_packet;
    rollback_count_ = rollback_count;
    total_frames_ = total_frames;

    // Estimate packet loss from frames without packets
    if (total_frames > 0) {
      packet_loss_pct_ = static_cast<double>(frames_without_packet) /
                         static_cast<double>(total_frames) * 100.0;
    }

    quality_ = ComputeQuality();
  }

  /// @brief Get full diagnostic report
  [[nodiscard]] DiagnosticReport GetReport() const {
    DiagnosticReport r;
    r.smoothed_rtt_ms = smoothed_rtt_;
    r.jitter_ms = jitter_;
    r.packet_loss_pct = packet_loss_pct_;
    r.prediction_accuracy = prediction_accuracy_;
    r.frames_without_packet = frames_without_packet_;
    r.total_frames = total_frames_;
    r.rollback_count = rollback_count_;
    r.quality = quality_;
    r.quality_str = QualityToString(quality_);
    r.overlay_text = FormatOverlay();
    return r;
  }

  /// @brief Format overlay text for display
  [[nodiscard]] std::string FormatOverlay() const {
    char buf[512];
    snprintf(buf, sizeof(buf),
             "NET: %s | RTT: %.0fms | Jitter: %.1fms | "
             "Loss: %.1f%% | Pred: %.0f%% | Rollbacks: %d",
             QualityToString(quality_),
             smoothed_rtt_, jitter_,
             packet_loss_pct_,
             prediction_accuracy_ * 100.0,
             rollback_count_);
    return buf;
  }

  /// @brief Get current quality rating
  [[nodiscard]] NetworkQuality GetQuality() const { return quality_; }

  /// @brief Get smoothed RTT
  [[nodiscard]] double GetSmoothedRTT() const { return smoothed_rtt_; }

  /// @brief Get jitter
  [[nodiscard]] double GetJitter() const { return jitter_; }

  /// @brief Get packet loss percentage
  [[nodiscard]] double GetPacketLoss() const { return packet_loss_pct_; }

  /// @brief Get prediction accuracy
  [[nodiscard]] double GetPredictionAccuracy() const { return prediction_accuracy_; }

  /// @brief Convert quality enum to string
  static const char* QualityToString(NetworkQuality q) {
    switch (q) {
      case NetworkQuality::kExcellent: return "Excellent";
      case NetworkQuality::kGood: return "Good";
      case NetworkQuality::kFair: return "Fair";
      case NetworkQuality::kPoor: return "Poor";
      case NetworkQuality::kCritical: return "Critical";
    }
    return "Unknown";
  }

 private:
  static constexpr size_t kMaxSamples = 60;

  NetworkQuality ComputeQuality() const {
    if (smoothed_rtt_ >= 500.0 || packet_loss_pct_ > 10.0)
      return NetworkQuality::kCritical;
    if (smoothed_rtt_ >= 200.0 || jitter_ >= 30.0)
      return NetworkQuality::kPoor;
    if (smoothed_rtt_ >= 100.0 || jitter_ >= 15.0)
      return NetworkQuality::kFair;
    if (smoothed_rtt_ >= 50.0 || jitter_ >= 5.0)
      return NetworkQuality::kGood;
    return NetworkQuality::kExcellent;
  }

  double SmoothedValue(const std::deque<double>& samples) const {
    if (samples.empty()) return 0.0;
    double sum = 0.0;
    for (double v : samples) sum += v;
    return sum / samples.size();
  }

  std::deque<double> rtt_samples_;
  double smoothed_rtt_ = 0.0;
  double jitter_ = 0.0;
  double packet_loss_pct_ = 0.0;
  double prediction_accuracy_ = 1.0;
  int frames_without_packet_ = 0;
  int total_frames_ = 0;
  int rollback_count_ = 0;
  NetworkQuality quality_ = NetworkQuality::kExcellent;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_NETWORK_DIAGNOSTICS_HPP
