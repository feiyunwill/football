// Copyright 2026 Google LLC & Contributors
// Shared TCP/UDP prediction and reconciliation, reviewed 2026-09-09.
#ifndef GFOOTBALL_FRAME_SYNC_FRAME_SIMULATION_HPP
#define GFOOTBALL_FRAME_SYNC_FRAME_SIMULATION_HPP

#include "frame_sync/engine_integration.hpp"
#include <algorithm>
#include <map>
#include <optional>
#include <stdexcept>
#include <utility>

namespace frame_sync {

class FrameSimulation {
 public:
  struct Confirmation {
    frame_id_t frame;
    std::vector<SlotInput> inputs;
    uint64_t hash;
    bool was_predicted;
    bool prediction_correct;
  };
  struct TickResult {
    bool predicted = false;
    bool rolled_back = false;
    bool prediction_limited = false;  // memory budget; authority still progresses
    std::vector<Confirmation> confirmed;
  };

  // 2026-09-09: validate cardinality before allocating any input history.
  // FrameSimulation(EngineCallbacks engine, size_t slots)
  //     : engine_(std::move(engine)), last_inputs_(slots, SlotInput::Default()) {
  //   if (slots == 0 || !engine_.step_frame || !engine_.save_state || !engine_.restore_state)
  // 2026-09-09: resume a restored authoritative boundary without replaying frame zero.
//   FrameSimulation(EngineCallbacks engine, size_t slots,
//                   SnapshotBudget budget = SnapshotBudget{})
//       : budget_(budget.snapshot_bytes, budget.history_bytes),
//         engine_(std::move(engine)),
//         last_inputs_(CheckedControlledSlots(slots), SlotInput::Default()) {
//     if (!engine_.step_frame || !engine_.save_state || !engine_.restore_state)
//       throw std::invalid_argument("FrameSimulation needs complete frame callbacks and slots");
//   }
  FrameSimulation(EngineCallbacks engine, size_t slots,
                  SnapshotBudget budget = SnapshotBudget{}, frame_id_t starting_frame = 0)
      : budget_(budget.snapshot_bytes, budget.history_bytes),
        engine_(std::move(engine)),
        last_inputs_(CheckedControlledSlots(slots), SlotInput::Default()),
        next_frame_(starting_frame), confirmed_count_(starting_frame) {
    if (!engine_.step_frame || !engine_.save_state || !engine_.restore_state)
      throw std::invalid_argument("FrameSimulation needs complete frame callbacks and slots");
    if (starting_frame > UINT32_MAX - kMaxBufferedAuthorityFrames)
      throw std::invalid_argument("Snapshot frame leaves no reconciliation window");
  }
  ~FrameSimulation() = default;
  FrameSimulation(const FrameSimulation&) = delete;
  FrameSimulation& operator=(const FrameSimulation&) = delete;
  FrameSimulation(FrameSimulation&&) = delete;
  FrameSimulation& operator=(FrameSimulation&&) = delete;

  // 2026-09-09: never retain an arbitrarily oversized caller vector capacity.
  // bool QueueAuthority(frame_id_t frame, std::vector<SlotInput> inputs) {
  bool QueueAuthority(frame_id_t frame, const std::vector<SlotInput>& inputs) {
    if (inputs.size() != last_inputs_.size() ||
        !std::all_of(inputs.begin(), inputs.end(), IsValidSlotInput)) return false;
    if (frame < confirmed_count_) return true;
    if (frame - confirmed_count_ >= kReceiveWindow) return false;
    // pending_.try_emplace(frame, std::move(inputs));
    if (pending_.contains(frame)) return true;
    std::vector<SlotInput> owned(inputs.begin(), inputs.end());
    const auto bytes = RetainedBytes(owned);
    if (bytes > kMaxBufferedInputBytes - pending_bytes_) return false;
    pending_.try_emplace(frame, std::move(owned));
    pending_bytes_ += bytes;
    return true;
  }

  // 2026-09-13: keep the fixed-input API as a compatibility wrapper.
  TickResult Tick(const SlotInput& input, std::span<const uint16_t> local_slots,
                  int max_predict = MAX_PREDICT_AHEAD_FRAMES) {
    return TickWithInputProvider([&input](frame_id_t) { return input; }, local_slots, max_predict);
  }

  // Previous signature/body entry:
  // TickResult Tick(const SlotInput& input, std::span<const uint16_t> local_slots,
  //                 int max_predict = MAX_PREDICT_AHEAD_FRAMES) {
  //   TickResult result;
  template<class InputProvider>
  TickResult TickWithInputProvider(InputProvider&& provide, std::span<const uint16_t> local_slots,
                                  int max_predict = MAX_PREDICT_AHEAD_FRAMES) {
    if (providing_input_) throw std::logic_error("Input provider must not reenter simulation");
    TickResult result;
    // Authority must always be consumed, including when prediction is suspended.
    for (int count = 0; count < kMaxCatchupFramesPerTick; ++count) {
      auto incoming = pending_.find(confirmed_count_);
      if (incoming == pending_.end()) break;
      const auto frame = confirmed_count_;
      auto history = history_.find(frame);
      const bool predicted = history != history_.end();
      const bool correct = predicted && SameInputs(history->second.inputs, incoming->second);
      uint64_t hash = 0;
      if (predicted && !correct) {
        engine_.restore_state(history->second.before);
        history->second.inputs = incoming->second;
        // 2026-09-09: keep the original pre-correction snapshot until the
        // authoritative frame commits. It is the recovery point if a later
        // prediction grows beyond the budget or its save callback throws.
        // for (auto it = history; it != history_.end(); ++it) {
        //   it->second.before = engine_.save_state();
        //   engine_.step_frame(it->second.inputs);
        //   it->second.hash = Hash();
        // }
        engine_.step_frame(history->second.inputs);
        history->second.hash = Hash();
        try {
          for (auto it = std::next(history); it != history_.end(); ++it) {
            StateBlob before = engine_.save_state();
            const auto old_bytes = SnapshotBytes(it->second);
            if (!Fits(before, it->second.inputs, history_bytes_ - old_bytes)) {
              RecoverCorrection(history);
              result.prediction_limited = true;
              break;
            }
            history_bytes_ -= old_bytes;
            it->second.before = std::move(before);
            history_bytes_ += SnapshotBytes(it->second);
            engine_.step_frame(it->second.inputs);
            it->second.hash = Hash();
          }
        } catch (...) {
          RecoverCorrection(history);
          throw;
        }
        ++rollback_count_;
        result.rolled_back = true;
      }
      if (predicted) {
        hash = history->second.hash;
        history_bytes_ -= SnapshotBytes(history->second);
        history_.erase(history);
      } else {
        engine_.step_frame(incoming->second);
        hash = Hash();
        ++next_frame_;
      }
      last_inputs_ = incoming->second;
      confirmed_hashes_[frame] = hash;
      result.confirmed.push_back({frame, incoming->second, hash, predicted, correct});
      pending_bytes_ -= RetainedBytes(incoming->second);
      pending_.erase(incoming);
      ++confirmed_count_;
      while (confirmed_hashes_.size() > kReceiveWindow) confirmed_hashes_.erase(confirmed_hashes_.begin());
    }

    // 2026-09-09: stopped peers can remain absent indefinitely without overflow.
    // if (result.confirmed.empty()) ++ticks_without_authority_;
    if (result.confirmed.empty())
      ticks_without_authority_ = std::min(ticks_without_authority_ + 1, MAX_FRAMES_WITHOUT_PACKET);
    else ticks_without_authority_ = 0;
    // 2026-09-13: the host samples/sends at the actual post-authority frame.
    // This still runs when prediction is limited: the server needs the input.
    for (uint16_t slot : local_slots)
      if (slot >= last_inputs_.size()) return result;
    SlotInput input;
    providing_input_ = true;
    try {
      input = std::invoke(std::forward<InputProvider>(provide), next_frame_);
    } catch (...) {
      providing_input_ = false;
      throw;
    }
    providing_input_ = false;
    if (result.prediction_limited) return result;
    if (ticks_without_authority_ >= MAX_FRAMES_WITHOUT_PACKET) return result;

    // Keep a bounded history. Frame zero is valid; confirmed_count is a count.
    max_predict = std::clamp(max_predict, 0, 8);
    if (next_frame_ - confirmed_count_ >= static_cast<unsigned>(max_predict)) return result;
    if (!IsValidSlotInput(input)) return result;
    auto inputs = last_inputs_;
    for (uint16_t slot : local_slots) {
      if (slot >= inputs.size()) return result;
      inputs[slot] = input;
    }
    Snapshot snapshot{engine_.save_state(), std::move(inputs), 0};
    // 2026-09-09: reject before stepping, and allocate the history node first.
    // engine_.step_frame(snapshot.inputs);
    // snapshot.hash = Hash();
    // history_.emplace(next_frame_++, std::move(snapshot));
    if (!Fits(snapshot.before, snapshot.inputs, history_bytes_)) {
      result.prediction_limited = true;
      return result;
    }
    auto [entry, inserted] = history_.emplace(next_frame_, std::move(snapshot));
    if (!inserted) throw std::logic_error("Prediction history already contains next frame");
    try {
      engine_.step_frame(entry->second.inputs);
      entry->second.hash = Hash();
    } catch (...) {
      auto failed = history_.extract(entry);
      engine_.restore_state(failed.mapped().before);
      throw;
    }
    history_bytes_ += SnapshotBytes(entry->second);
    ++next_frame_;
    result.predicted = true;
    return result;
  }

  std::optional<bool> VerifyHash(frame_id_t frame, uint64_t hash) const {
    auto it = confirmed_hashes_.find(frame);
    if (it == confirmed_hashes_.end()) return std::nullopt;
    return it->second == hash;
  }
  frame_id_t next_frame() const { return next_frame_; }
  frame_id_t confirmed_count() const { return confirmed_count_; }
  int rollback_count() const { return rollback_count_; }
  size_t history_size() const { return history_.size(); }
  size_t history_bytes() const { return history_bytes_; }
  size_t pending_size() const { return pending_.size(); }
  size_t pending_bytes() const { return pending_bytes_; }

 private:
  struct Snapshot {
    StateBlob before;
    std::vector<SlotInput> inputs;
    uint64_t hash;
  };
  static size_t SnapshotBytes(const Snapshot& snapshot) {
    return RetainedBytes(snapshot.before) + RetainedBytes(snapshot.inputs);
  }
  bool Fits(const StateBlob& state, const std::vector<SlotInput>& inputs,
            size_t retained) const {
    const auto state_bytes = RetainedBytes(state);
    const auto input_bytes = RetainedBytes(inputs);
    return state_bytes <= budget_.snapshot_bytes &&
           input_bytes <= budget_.history_bytes &&
           state_bytes <= budget_.history_bytes - input_bytes &&
           retained <= budget_.history_bytes - input_bytes - state_bytes;
  }
  // Discard later speculation and leave the engine exactly after the corrected
  // authoritative frame. Its pre-state remains until confirmation is committed.
  void RecoverCorrection(std::map<frame_id_t, Snapshot>::iterator root) {
    engine_.restore_state(root->second.before);
    engine_.step_frame(root->second.inputs);
    root->second.hash = Hash();
    for (auto it = std::next(root); it != history_.end();) {
      history_bytes_ -= SnapshotBytes(it->second);
      it = history_.erase(it);
    }
    next_frame_ = root->first + 1;
  }
  static bool SameInputs(const std::vector<SlotInput>& a, const std::vector<SlotInput>& b) {
    return std::equal(a.begin(), a.end(), b.begin(), b.end(), [](const auto& x, const auto& y) {
      return x.dir_x == y.dir_x && x.dir_y == y.dir_y && x.buttons == y.buttons;
    });
  }
  uint64_t Hash() const { return engine_.compute_hash ? engine_.compute_hash() : 0; }
  // 2026-09-09: shared cardinality bound plus separate retained input bytes.
  // static constexpr frame_id_t kReceiveWindow = 1024;
  static constexpr frame_id_t kReceiveWindow = kMaxBufferedAuthorityFrames;
  SnapshotBudget budget_;
  EngineCallbacks engine_;
  std::vector<SlotInput> last_inputs_;
  std::map<frame_id_t, Snapshot> history_;
  std::map<frame_id_t, std::vector<SlotInput>> pending_;
  std::map<frame_id_t, uint64_t> confirmed_hashes_;
  size_t history_bytes_ = 0;
  size_t pending_bytes_ = 0;
  frame_id_t next_frame_ = 0;
  frame_id_t confirmed_count_ = 0;
  int rollback_count_ = 0;
  int ticks_without_authority_ = 0;
  bool providing_input_ = false;
};
}  // namespace frame_sync
#endif
