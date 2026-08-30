// Copyright 2019 Google LLC & Contributors
// Jitter buffer statistics: tracks network quality metrics for frame sync.
// Monitors frame arrival jitter, RTT, packet loss, and recommends buffer size.

#ifndef GFOOTBALL_FRAME_SYNC_JITTER_STATS_HPP
#define GFOOTBALL_FRAME_SYNC_JITTER_STATS_HPP

#include <chrono>
#include <cmath>
#include <cstdint>
#include <deque>
#include <algorithm>
#include <numeric>

namespace frame_sync {

struct JitterStats {
  // Frame arrival timing
  double last_arrival_ms = 0.0;
  double avg_interval_ms = 0.0;
  double jitter_ms = 0.0;          // inter-frame jitter (standard deviation)
  double max_jitter_ms = 0.0;

  // Packet loss tracking
  int total_frames = 0;
  int received_frames = 0;
  int lost_frames = 0;
  float loss_rate = 0.0f;

  // RTT tracking (if ping/pong implemented)
  double avg_rtt_ms = 0.0;
  double max_rtt_ms = 0.0;

  // Recommended buffer size (in frames)
  int recommended_buffer_frames = 3;

  // Window for statistics (last N samples)
  static constexpr int kWindowSize = 100;

 private:
  std::deque<double> intervals_;
  std::deque<double> rtts_;

 public:
  // Record frame arrival
  void record_arrival(double now_ms) {
    if (last_arrival_ms > 0) {
      double interval = now_ms - last_arrival_ms;
      intervals_.push_back(interval);
      if (static_cast<int>(intervals_.size()) > kWindowSize) {
        intervals_.pop_front();
      }
      update_jitter();
    }
    last_arrival_ms = now_ms;
    ++received_frames;
    ++total_frames;
    update_loss_rate();
  }

  // Record a frame was expected but not received
  void record_lost() {
    ++lost_frames;
    ++total_frames;
    update_loss_rate();
  }

  // Record RTT sample
  void record_rtt(double rtt_ms) {
    rtts_.push_back(rtt_ms);
    if (static_cast<int>(rtts_.size()) > kWindowSize) {
      rtts_.pop_front();
    }
    if (!rtts_.empty()) {
      avg_rtt_ms = std::accumulate(rtts_.begin(), rtts_.end(), 0.0) / rtts_.size();
      max_rtt_ms = *std::max_element(rtts_.begin(), rtts_.end());
    }
  }

  // Get statistics summary
  std::string summary() const {
    char buf[256];
    std::snprintf(buf, sizeof(buf),
        "jitter=%.1fms loss=%.1f%% rtt=%.1fms buffer=%d",
        jitter_ms, loss_rate * 100.0f, avg_rtt_ms, recommended_buffer_frames);
    return std::string(buf);
  }

 private:
  void update_jitter() {
    if (intervals_.size() < 2) return;

    avg_interval_ms = std::accumulate(intervals_.begin(), intervals_.end(), 0.0)
                      / intervals_.size();

    // Compute standard deviation
    double sum_sq = 0.0;
    for (double v : intervals_) {
      double diff = v - avg_interval_ms;
      sum_sq += diff * diff;
    }
    jitter_ms = std::sqrt(sum_sq / intervals_.size());
    max_jitter_ms = std::max(max_jitter_ms, jitter_ms);

    // Recommend buffer size based on jitter
    // 1 frame = ~100ms at 10fps; buffer = ceil(jitter / frame_time) + 1
    double frame_time_ms = 100.0;  // 10 fps
    recommended_buffer_frames = std::max(2,
        static_cast<int>(std::ceil(jitter_ms / frame_time_ms)) + 2);
  }

  void update_loss_rate() {
    if (total_frames > 0) {
      loss_rate = static_cast<float>(lost_frames) / total_frames;
    }
  }
};

}  // namespace frame_sync

#endif
