// Copyright 2026 Google LLC & Contributors
// ClientState: ring buffer of game state snapshots for prediction/rollback.
//
// Design:
//   - Client saves a StateSnapshot (opaque byte blob from GameEnv::get_state)
//     every frame before stepping.
//   - When an authoritative frame arrives for frame_id N, the client:
//     1. Restores the snapshot saved at frame N.
//     2. Re-simulates from N using the authoritative inputs (not predicted).
//   - Ring buffer size = MAX_PREDICT_AHEAD_FRAMES + margin (default 8).
//   - All operations are pure C++ — no Python dependency.

#ifndef GFOOTBALL_FRAME_SYNC_CLIENT_STATE_HPP
#define GFOOTBALL_FRAME_SYNC_CLIENT_STATE_HPP

#include "frame_sync/protocol.hpp"
#include "frame_sync/memory_budget.hpp"

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <deque>
#include <functional>
#include <iterator>
#include <string>
#include <utility>
#include <unordered_map>
#include <vector>

namespace frame_sync {

// Opaque game state blob (output of GameEnv::get_state(""/"v2")).
using StateBlob = std::vector<uint8_t>;

// Callback types for engine integration. The client_state module does NOT
// depend on GameEnv directly; the host wires these in.
using SaveStateFn = std::function<StateBlob()>;
using RestoreStateFn = std::function<void(const StateBlob&)>;
using StepFn = std::function<void(const SlotInput& input)>;
using ComputeHashFn = std::function<uint64_t()>;

// Per-frame snapshot entry.
struct FrameSnapshot {
  frame_id_t frame_id = 0;
  StateBlob state;
  SlotInput predicted_input;  // what the client predicted for this frame
};

// Dynamic frame catching constants.
constexpr int kCatchupThresholdFrames = 2;       // start catching up when behind by this many frames
constexpr int kMaxCatchupFramesPerTick = 3;       // max frames to fast-forward in one tick
constexpr int kAheadThresholdFrames = 1;          // slow down when ahead by this many frames
constexpr double kJitterSmoothingWindowMs = 500.0; // jitter moving average window (ms)
constexpr double kJitterHighThresholdMs = 30.0;    // jitter above this → warn

// Ring buffer of recent frame snapshots, indexed by frame_id.
// Old entries beyond the buffer window are evicted automatically.
// 2026-09-05 优化: 使用 unordered_map 实现 O(1) 查找
class ClientState {
 public:
  // max_buffered: how many frames to keep in the ring buffer.
  // Must be >= MAX_PREDICT_AHEAD_FRAMES + 1.
  // 2026-09-09: reject invalid counts before constructing snapshot containers.
  // explicit ClientState(int max_buffered = MAX_PREDICT_AHEAD_FRAMES + 4)
  //     : max_buffered_(max_buffered) {}
  explicit ClientState(int max_buffered = MAX_PREDICT_AHEAD_FRAMES + 4,
                       SnapshotBudget budget = SnapshotBudget{})
      : max_buffered_(CheckedHistoryCount(max_buffered)),
        budget_(budget.snapshot_bytes, budget.history_bytes) {}
  ~ClientState() = default;
  ClientState(const ClientState&) = default;
  ClientState& operator=(const ClientState& other) {
    if (this != &other) {
      ClientState copy(other);
      Swap(copy);
    }
    return *this;
  }
  ClientState(ClientState&& other) : ClientState() { Swap(other); }
  ClientState& operator=(ClientState&& other) {
    if (this != &other) {
      ClientState moved(std::move(other));
      Swap(moved);
    }
    return *this;
  }

  // ----- Core API -----

  // Save a snapshot of the current engine state for the given frame.
  // Called BEFORE stepping the engine for this frame.
  void save_snapshot(frame_id_t frame_id, const SlotInput& predicted_input,
                     const SaveStateFn& save_fn);

  // Restore the engine to the snapshot at frame_id, then step it with the
  // given input. Returns true if snapshot was found and restored.
  // Called when an authoritative frame arrives for an already-predicted frame.
  bool rollback_to(frame_id_t frame_id, const SlotInput& auth_input,
                   const RestoreStateFn& restore_fn, const StepFn& step_fn);

  // Restore the engine to the snapshot at frame_id (without stepping).
  // Used when we need to re-simulate a range of frames.
  bool restore_snapshot(frame_id_t frame_id, const RestoreStateFn& restore_fn);

  // Get the snapshot for a frame_id, or nullptr if not found.
  const FrameSnapshot* get_snapshot(frame_id_t frame_id) const;

  // Evict snapshots older than (latest_frame_id - max_buffered_).
  void evict_old(frame_id_t latest_frame_id);

  // Rebuild the frame_to_index_ mapping after deque modifications.
  void RebuildIndex();

  // Clear all snapshots.
  void clear();

  // ----- Statistics -----
  int rollback_count() const { return rollback_count_; }
  int evict_count() const { return evict_count_; }
  int buffer_size() const { return static_cast<int>(snapshots_.size()); }
  size_t buffered_bytes() const { return buffered_bytes_; }

  // ----- State hash tracking -----
  // Record a state hash received from the server for a given frame.
  void record_server_hash(frame_id_t frame_id, uint64_t hash);

  // Check if a server hash matches the local hash at that frame.
  // Returns: match, mismatch, or unknown (no local hash available).
  enum class HashCheck : std::uint8_t { kMatch, kMismatch, kUnknown };
  HashCheck check_hash(frame_id_t frame_id, uint64_t local_hash) const;

  // Get the most recently received server hash, or 0 if none.
  frame_id_t last_server_hash_frame() const { return last_server_hash_frame_; }
  uint64_t last_server_hash() const { return last_server_hash_; }

 // ----- Dynamic frame catching -----

  // How many frames the client is behind the server.
  // Positive = behind, negative = ahead.
  int frames_behind(frame_id_t server_frame, frame_id_t local_frame) const {
    return static_cast<int>(server_frame) - static_cast<int>(local_frame);
  }

  // Should we catch up this tick? Returns the number of frames to process.
  // 0 = normal (process 1 frame), >0 = catch up N frames, <0 = wait.
  int catchup_count(frame_id_t server_frame, frame_id_t local_frame) const {
    int behind = frames_behind(server_frame, local_frame);
    if (behind > kCatchupThresholdFrames) {
      return std::min(behind, kMaxCatchupFramesPerTick);
    }
    if (behind < -kAheadThresholdFrames) {
      return -1;  // wait for server
    }
    return 1;  // normal
  }

  // ----- Jitter tracking -----

  // Record a frame arrival timestamp (monotonic clock, milliseconds).
  void record_frame_arrival(double timestamp_ms) {
    if (last_frame_arrival_ms_ > 0) {
      double interval = timestamp_ms - last_frame_arrival_ms_;
      frame_intervals_.push_back(interval);
      if (frame_intervals_.size() > 100) frame_intervals_.pop_front();
    }
    last_frame_arrival_ms_ = timestamp_ms;
  }

  // Average frame interval in ms.
  constexpr double avg_frame_interval_ms() const {
    if (frame_intervals_.empty()) return 0.0;
    double sum = 0.0;
    for (double v : frame_intervals_) sum += v;
    return sum / frame_intervals_.size();
  }

  // Current jitter: std dev of frame intervals.
  double jitter_ms() const {
    if (frame_intervals_.size() < 2) return 0.0;
    double avg = avg_frame_interval_ms();
    double sum_sq = 0.0;
    for (double v : frame_intervals_) {
      double diff = v - avg;
      sum_sq += diff * diff;
    }
    return std::sqrt(sum_sq / frame_intervals_.size());
  }

  // Is jitter above the high threshold?
  bool is_jitter_high() const { return jitter_ms() > kJitterHighThresholdMs; }

  // ----- Statistics (extended) -----
  int catchup_count_total() const { return catchup_count_total_; }
  int wait_count_total() const { return wait_count_total_; }

 private:
  void Swap(ClientState& other) noexcept {
    using std::swap;
    swap(max_buffered_, other.max_buffered_);
    swap(budget_, other.budget_);
    swap(buffered_bytes_, other.buffered_bytes_);
    swap(snapshots_, other.snapshots_);
    swap(frame_to_index_, other.frame_to_index_);
    swap(rollback_count_, other.rollback_count_);
    swap(evict_count_, other.evict_count_);
    swap(last_server_hash_frame_, other.last_server_hash_frame_);
    swap(last_server_hash_, other.last_server_hash_);
    swap(last_frame_arrival_ms_, other.last_frame_arrival_ms_);
    swap(frame_intervals_, other.frame_intervals_);
    swap(catchup_count_total_, other.catchup_count_total_);
    swap(wait_count_total_, other.wait_count_total_);
  }
  static int CheckedHistoryCount(int count) {
    if (count <= 0 || static_cast<size_t>(count) > kMaxSnapshotHistoryFrames)
      throw std::invalid_argument("Snapshot history count must be in [1, 1024]");
    return count;
  }
  int max_buffered_;
  SnapshotBudget budget_;
  size_t buffered_bytes_ = 0;
  // Use a deque for O(1) push_back/evict.
  // 2026-09-05 优化: 添加 unordered_map 索引实现 O(1) 查找
  std::deque<FrameSnapshot> snapshots_;
  std::unordered_map<frame_id_t, size_t> frame_to_index_;  // frame_id -> snapshots_ 下标
  int rollback_count_ = 0;
  int evict_count_ = 0;

  // Server state hashes for verification.
  frame_id_t last_server_hash_frame_ = 0;
  uint64_t last_server_hash_ = 0;

  // Jitter tracking.
  double last_frame_arrival_ms_ = 0.0;
  std::deque<double> frame_intervals_;

  // Catch-up statistics.
  int catchup_count_total_ = 0;
  int wait_count_total_ = 0;
};

// ----- Inline implementation (header-only for simplicity) -----

inline void ClientState::save_snapshot(frame_id_t frame_id,
                                       const SlotInput& predicted_input,
                                       const SaveStateFn& save_fn) {
  // 2026-09-09: validate first; failed saves leave the current history intact.
  // FrameSnapshot snap;
  // snap.frame_id = frame_id;
  // snap.predicted_input = predicted_input;
  // snap.state = save_fn();
  // snapshots_.push_back(std::move(snap));
  // frame_to_index_[frame_id] = snapshots_.size() - 1;
  // evict_old(frame_id);
  if (!save_fn || !IsValidSlotInput(predicted_input))
    throw std::invalid_argument("Snapshot needs a callback and valid input");
  StateBlob state = save_fn();
  const auto bytes = RetainedBytes(state);
  if (bytes > budget_.snapshot_bytes)
    throw std::length_error("Snapshot exceeds its retained byte budget");
  const auto existing = frame_to_index_.find(frame_id);
  if (existing != frame_to_index_.end()) {
    auto& snapshot = snapshots_[existing->second];
    buffered_bytes_ -= RetainedBytes(snapshot.state);
    snapshot.state = std::move(state);
    snapshot.predicted_input = predicted_input;
    buffered_bytes_ += bytes;
  } else {
    // Allocate the index before deque insertion and undo it on allocation failure.
    const auto index = snapshots_.size();
    auto [entry, inserted] = frame_to_index_.emplace(frame_id, index);
    try {
      snapshots_.push_back({frame_id, std::move(state), predicted_input});
    } catch (...) {
      frame_to_index_.erase(entry);
      throw;
    }
    buffered_bytes_ += bytes;
  }
  evict_old(frame_id);
}

inline bool ClientState::rollback_to(frame_id_t frame_id,
                                     const SlotInput& auth_input,
                                     const RestoreStateFn& restore_fn,
                                     const StepFn& step_fn) {
  const FrameSnapshot* snap = get_snapshot(frame_id);
  if (!snap) return false;
  // 2026-09-09: reject an invalid correction before restoring or stepping.
  if (!IsValidSlotInput(auth_input) || !restore_fn || !step_fn)
    throw std::invalid_argument("Rollback needs valid input and callbacks");
  restore_fn(snap->state);
  step_fn(auth_input);
  ++rollback_count_;
  return true;
}

inline bool ClientState::restore_snapshot(frame_id_t frame_id,
                                         const RestoreStateFn& restore_fn) {
  const FrameSnapshot* snap = get_snapshot(frame_id);
  if (!snap) return false;
  if (!restore_fn) throw std::invalid_argument("Restore callback is missing");
  restore_fn(snap->state);
  return true;
}

inline const FrameSnapshot* ClientState::get_snapshot(frame_id_t frame_id) const {
  // 2026-09-05 优化: O(1) 查找
  auto it = frame_to_index_.find(frame_id);
  if (it == frame_to_index_.end()) return nullptr;
  return &snapshots_[it->second];
}

inline void ClientState::evict_old(frame_id_t latest_frame_id) {
  // 2026-09-09: enforce retained bytes as well as frame count. A replaced frame
  // remains available even when other frames must be evicted to make room.
  // while (static_cast<int>(snapshots_.size()) > max_buffered_) {
  while (static_cast<int>(snapshots_.size()) > max_buffered_ ||
         buffered_bytes_ > budget_.history_bytes) {
    if (snapshots_.front().frame_id == latest_frame_id && snapshots_.size() > 1) {
      const auto victim = std::next(snapshots_.begin());
      buffered_bytes_ -= RetainedBytes(victim->state);
      frame_to_index_.erase(victim->frame_id);
      snapshots_.erase(victim);
      ++evict_count_;
      continue;
    }
    // 2026-09-05 优化: 移除索引
    frame_to_index_.erase(snapshots_.front().frame_id);
    buffered_bytes_ -= RetainedBytes(snapshots_.front().state);
    snapshots_.pop_front();
    ++evict_count_;
  }
  // 2026-09-05 优化: 重建索引（因为 deque 的下标会变化）
  RebuildIndex();
}

inline void ClientState::RebuildIndex() {
  // 2026-09-09: all surviving keys already exist; rebuilding must not allocate
  // or leave a partial index after history has been committed.
  // frame_to_index_.clear();
  // for (size_t i = 0; i < snapshots_.size(); ++i) {
  //   frame_to_index_[snapshots_[i].frame_id] = i;
  // }
  for (size_t i = 0; i < snapshots_.size(); ++i)
    frame_to_index_.at(snapshots_[i].frame_id) = i;
}

inline void ClientState::clear() {
  snapshots_.clear();
  buffered_bytes_ = 0;
  frame_to_index_.clear();  // 2026-09-05 优化: 清空索引
  rollback_count_ = 0;
  evict_count_ = 0;
  last_server_hash_frame_ = 0;
  last_server_hash_ = 0;
  last_frame_arrival_ms_ = 0.0;
  frame_intervals_.clear();
  catchup_count_total_ = 0;
  wait_count_total_ = 0;
}

inline void ClientState::record_server_hash(frame_id_t frame_id, uint64_t hash) {
  last_server_hash_frame_ = frame_id;
  last_server_hash_ = hash;
}

inline ClientState::HashCheck ClientState::check_hash(frame_id_t frame_id,
                                                      uint64_t local_hash) const {
  if (last_server_hash_frame_ != frame_id) return HashCheck::kUnknown;
  return (last_server_hash_ == local_hash) ? HashCheck::kMatch : HashCheck::kMismatch;
}

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_CLIENT_STATE_HPP
