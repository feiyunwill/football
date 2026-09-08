// Copyright 2026 Google LLC & Contributors
// Prediction Accuracy Tracker for frame sync (ms-16.5).
// Compares predicted state hashes against authoritative frames to measure
// prediction accuracy over sliding windows.
//
// Usage:
//   PredictionAccuracyTracker tracker;
//   tracker.RecordPrediction(frame, predicted_hash);
//   // ... later when authoritative frame arrives ...
//   tracker.RecordAuthoritative(frame, authoritative_hash);
//   auto accuracy = tracker.GetAccuracy();
//   auto trend = tracker.GetAccuracyTrend();

#ifndef GFOOTBALL_FRAME_SYNC_PREDICTION_ACCURACY_TRACKER_HPP
#define GFOOTBALL_FRAME_SYNC_PREDICTION_ACCURACY_TRACKER_HPP

#include <cstdint>
#include <deque>
#include <optional>
#include <vector>

namespace frame_sync {

/// @brief Prediction accuracy tracker
///
/// Tracks prediction correctness by comparing predicted state hashes against
/// authoritative state hashes. Provides accuracy metrics over sliding windows
/// and trend analysis.
class PredictionAccuracyTracker {
 public:
  /// @brief Accuracy trend direction
  enum class Trend { kImproving, kStable, kDegrading };

  PredictionAccuracyTracker() = default;

  /// @brief Record a predicted state hash for a frame
  /// @param frame Frame number
  /// @param predicted_hash State hash predicted by client
  void RecordPrediction(uint32_t frame, uint64_t predicted_hash) {
    predictions_[frame] = predicted_hash;
    Cleanup(frame);
  }

  /// @brief Record authoritative state hash for a frame
  /// @param frame Frame number
  /// @param authoritative_hash State hash from server
  /// @return true if prediction was correct, false if mismatch, std::nullopt if no prediction
  [[nodiscard]] std::optional<bool> RecordAuthoritative(uint32_t frame, 
                                                         uint64_t authoritative_hash) {
    auto it = predictions_.find(frame);
    if (it == predictions_.end()) {
      return std::nullopt;  // No prediction for this frame
    }

    bool correct = (it->second == authoritative_hash);
    
    // Record result
    results_.push_back(correct);
    if (results_.size() > kMaxSamples) {
      results_.pop_front();
    }

    if (!correct) {
      mismatch_frames_.push_back(frame);
      if (mismatch_frames_.size() > kMaxMismatches) {
        mismatch_frames_.pop_front();
      }
    }

    total_frames_++;
    if (correct) correct_frames_++;

    predictions_.erase(it);
    return correct;
  }

  /// @brief Get current prediction accuracy
  /// @return Accuracy ratio (0.0 - 1.0)
  [[nodiscard]] constexpr double GetAccuracy() const {
    if (total_frames_ == 0) return 1.0;
    return static_cast<double>(correct_frames_) / total_frames_;
  }

  /// @brief Get accuracy over recent window
  /// @param window_size Number of recent frames to consider
  /// @return Accuracy ratio over window
  [[nodiscard]] double GetRecentAccuracy(size_t window_size = 50) const {
    if (results_.empty()) return 1.0;
    
    size_t start = (results_.size() > window_size) ? results_.size() - window_size : 0;
    size_t recent_correct = 0;
    size_t recent_total = 0;
    
    for (size_t i = start; i < results_.size(); ++i) {
      recent_total++;
      if (results_[i]) recent_correct++;
    }
    
    if (recent_total == 0) return 1.0;
    return static_cast<double>(recent_correct) / recent_total;
  }

  /// @brief Get accuracy trend (improving, stable, degrading)
  [[nodiscard]] constexpr Trend GetAccuracyTrend() const {
    if (results_.size() < 20) return Trend::kStable;
    
    size_t half = results_.size() / 2;
    size_t old_correct = 0, new_correct = 0;
    
    for (size_t i = 0; i < half; ++i) {
      if (results_[i]) old_correct++;
    }
    for (size_t i = half; i < results_.size(); ++i) {
      if (results_[i]) new_correct++;
    }
    
    double old_accuracy = static_cast<double>(old_correct) / half;
    double new_accuracy = static_cast<double>(new_correct) / (results_.size() - half);
    
    double diff = new_accuracy - old_accuracy;
    if (diff > 0.05) return Trend::kImproving;
    if (diff < -0.05) return Trend::kDegrading;
    return Trend::kStable;
  }

  /// @brief Get total frames tracked
  [[nodiscard]] uint64_t GetTotalFrames() const { return total_frames_; }

  /// @brief Get number of correct predictions
  [[nodiscard]] uint64_t GetCorrectFrames() const { return correct_frames_; }

  /// @brief Get recent mismatch frame numbers
  [[nodiscard]] const std::deque<uint32_t>& GetRecentMismatches() const {
    return mismatch_frames_;
  }

  /// @brief Check if there are pending predictions
  [[nodiscard]] bool HasPendingPredictions() const { return !predictions_.empty(); }

  /// @brief Get number of pending predictions
  [[nodiscard]] size_t GetPendingCount() const { return predictions_.size(); }

  /// @brief Reset all statistics
  void Reset() {
    predictions_.clear();
    results_.clear();
    mismatch_frames_.clear();
    total_frames_ = 0;
    correct_frames_ = 0;
  }

 private:
  static constexpr size_t kMaxSamples = 200;
  static constexpr size_t kMaxMismatches = 20;

  /// @brief Cleanup old predictions to prevent memory growth
  void Cleanup(uint32_t current_frame) {
    if (current_frame < 100) return;  // Avoid underflow
    uint32_t cutoff = current_frame - 100;
    for (auto it = predictions_.begin(); it != predictions_.end(); ) {
      if (it->first < cutoff) {
        it = predictions_.erase(it);
      } else {
        ++it;
      }
    }
  }

  std::unordered_map<uint32_t, uint64_t> predictions_;  // frame -> predicted hash
  std::deque<bool> results_;                            // sliding window of results
  std::deque<uint32_t> mismatch_frames_;                // recent mismatch frames

  uint64_t total_frames_ = 0;
  uint64_t correct_frames_ = 0;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_PREDICTION_ACCURACY_TRACKER_HPP
