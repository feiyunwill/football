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

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <deque>
#include <functional>
#include <string>
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

// Ring buffer of recent frame snapshots, indexed by frame_id.
// Old entries beyond the buffer window are evicted automatically.
class ClientState {
 public:
  // max_buffered: how many frames to keep in the ring buffer.
  // Must be >= MAX_PREDICT_AHEAD_FRAMES + 1.
  explicit ClientState(int max_buffered = MAX_PREDICT_AHEAD_FRAMES + 4)
      : max_buffered_(max_buffered) {}

  // ----- Core API -----

  // Save a snapshot of the current engine state for the given frame.
  // Called BEFORE stepping the engine for this frame.
  void save_snapshot(frame_id_t frame_id, const SlotInput& predicted_input,
                     SaveStateFn save_fn);

  // Restore the engine to the snapshot at frame_id, then step it with the
  // given input. Returns true if snapshot was found and restored.
  // Called when an authoritative frame arrives for an already-predicted frame.
  bool rollback_to(frame_id_t frame_id, const SlotInput& auth_input,
                   RestoreStateFn restore_fn, StepFn step_fn);

  // Restore the engine to the snapshot at frame_id (without stepping).
  // Used when we need to re-simulate a range of frames.
  bool restore_snapshot(frame_id_t frame_id, RestoreStateFn restore_fn);

  // Get the snapshot for a frame_id, or nullptr if not found.
  const FrameSnapshot* get_snapshot(frame_id_t frame_id) const;

  // Evict snapshots older than (latest_frame_id - max_buffered_).
  void evict_old(frame_id_t latest_frame_id);

  // Clear all snapshots.
  void clear();

  // ----- Statistics -----
  int rollback_count() const { return rollback_count_; }
  int evict_count() const { return evict_count_; }
  int buffer_size() const { return static_cast<int>(snapshots_.size()); }

  // ----- State hash tracking -----
  // Record a state hash received from the server for a given frame.
  void record_server_hash(frame_id_t frame_id, uint64_t hash);

  // Check if a server hash matches the local hash at that frame.
  // Returns: match, mismatch, or unknown (no local hash available).
  enum class HashCheck { kMatch, kMismatch, kUnknown };
  HashCheck check_hash(frame_id_t frame_id, uint64_t local_hash) const;

  // Get the most recently received server hash, or 0 if none.
  frame_id_t last_server_hash_frame() const { return last_server_hash_frame_; }
  uint64_t last_server_hash() const { return last_server_hash_; }

 private:
  int max_buffered_;
  // Use a deque for O(1) push_back/evict and O(n) lookup by frame_id.
  // The buffer is small (8 entries), so linear scan is fine.
  std::deque<FrameSnapshot> snapshots_;
  int rollback_count_ = 0;
  int evict_count_ = 0;

  // Server state hashes for verification.
  frame_id_t last_server_hash_frame_ = 0;
  uint64_t last_server_hash_ = 0;
};

// ----- Inline implementation (header-only for simplicity) -----

inline void ClientState::save_snapshot(frame_id_t frame_id,
                                       const SlotInput& predicted_input,
                                       SaveStateFn save_fn) {
  FrameSnapshot snap;
  snap.frame_id = frame_id;
  snap.predicted_input = predicted_input;
  snap.state = save_fn();
  snapshots_.push_back(std::move(snap));
  evict_old(frame_id);
}

inline bool ClientState::rollback_to(frame_id_t frame_id,
                                     const SlotInput& auth_input,
                                     RestoreStateFn restore_fn,
                                     StepFn step_fn) {
  const FrameSnapshot* snap = get_snapshot(frame_id);
  if (!snap) return false;
  restore_fn(snap->state);
  step_fn(auth_input);
  ++rollback_count_;
  return true;
}

inline bool ClientState::restore_snapshot(frame_id_t frame_id,
                                         RestoreStateFn restore_fn) {
  const FrameSnapshot* snap = get_snapshot(frame_id);
  if (!snap) return false;
  restore_fn(snap->state);
  return true;
}

inline const FrameSnapshot* ClientState::get_snapshot(frame_id_t frame_id) const {
  for (const auto& snap : snapshots_) {
    if (snap.frame_id == frame_id) return &snap;
  }
  return nullptr;
}

inline void ClientState::evict_old(frame_id_t latest_frame_id) {
  while (static_cast<int>(snapshots_.size()) > max_buffered_) {
    snapshots_.pop_front();
    ++evict_count_;
  }
}

inline void ClientState::clear() {
  snapshots_.clear();
  rollback_count_ = 0;
  evict_count_ = 0;
  last_server_hash_frame_ = 0;
  last_server_hash_ = 0;
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
