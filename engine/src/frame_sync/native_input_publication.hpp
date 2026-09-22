// 2026-09-13: publish before engine catchup; rendering must not make every input arrive stale.
#pragma once
#include "frame_sync/local_input_history.hpp"
#include <algorithm>
// 2026-09-13: publication and prediction share one bounded retained history.
// #include <cstdint>
#include <cstdint>
#include <mutex>
#include <chrono>
#include "frame_sync/native_publication_clock.hpp"
namespace frame_sync {
// One future collection beyond the most recently received authority leaves a
// bounded transport opportunity. This is input scheduling, not a latency claim.
inline frame_id_t NativeInputTarget(frame_id_t authority_count,frame_id_t next_simulation) {
  const uint64_t target=std::max(uint64_t(authority_count)+1,uint64_t(next_simulation));
  if(target>=UINT32_MAX)throw std::overflow_error("Native input schedule exhausted");
  return static_cast<frame_id_t>(target);
}
template<class Sample,class Send>
frame_id_t PublishNativeInput(LocalInputHistory& history,frame_id_t confirmed_count,
                              frame_id_t authority_count,frame_id_t next_simulation,
                              Sample&& sample,Send&& send) {
  const auto target=NativeInputTarget(authority_count,next_simulation);
  history.Confirm(confirmed_count);
  const auto [input,fresh]=history.ForFrame(target,std::forward<Sample>(sample));
  if(fresh && !std::invoke(std::forward<Send>(send),target,input))
    throw std::runtime_error("Failed to publish native input");
  return target;
}
// 2026-09-13: serialize immutable frame publication without exposing GameEnv to the transport worker.
// } // namespace frame_sync
// The transport never reads FrameSimulation. Its owner publishes frame boundaries.
// Lock order is publication -> sampled input -> transport; receiver callbacks
// only own transport state and never enter this history.
class NativePublishedHistory {
 public:
  using Clock = std::int64_t (*)();
  // 2026-09-13: capture publication time inside the same serialization as the ledger.
  // explicit NativePublishedHistory(LocalInputHistory& history) : history_(history) {}
  explicit NativePublishedHistory(LocalInputHistory& history, Clock clock = Now)
      : history_(history), clock_(clock) {
    if (!clock_) throw std::invalid_argument("Native publication needs a clock");
  }
  ~NativePublishedHistory() = default;
  NativePublishedHistory(const NativePublishedHistory&) = delete;
  NativePublishedHistory& operator=(const NativePublishedHistory&) = delete;
  NativePublishedHistory(NativePublishedHistory&&) = delete;
  NativePublishedHistory& operator=(NativePublishedHistory&&) = delete;

  // 2026-09-14: discard unsent/cached input and timing from the previous physical connection.
  // The caller serializes reset with capture of its transport generation.
  void Reset(frame_id_t starting_frame) {
    std::lock_guard lock(mu_);
    history_.Reset(starting_frame);schedule_ = NativePublicationClock{};next_ = starting_frame;
  }

  void Advance(frame_id_t next,frame_id_t confirmed) {
    std::lock_guard lock(mu_);
    if (next<confirmed) throw std::invalid_argument("Published simulation boundary precedes authority");
    history_.Confirm(confirmed);next_=next;
  }
  SlotInput Read(frame_id_t frame,frame_id_t confirmed) {
    std::lock_guard lock(mu_);
    if (frame<confirmed) throw std::invalid_argument("Predicted input precedes authority");
    history_.Confirm(confirmed);next_=frame;
    return history_.Find(frame).value_or(SlotInput::Default());
  }
  template<class Sample,class Send>
  frame_id_t Publish(frame_id_t authority,Sample&& sample,Send&& send) {
    std::lock_guard lock(mu_);
    return PublishNativeInput(history_,history_.confirmed_count(),authority,next_,
                              std::forward<Sample>(sample),std::forward<Send>(send));
  }
  template<class Sample,class Send>
  std::optional<frame_id_t> PublishTimed(frame_id_t authority,Sample&& sample,Send&& send) {
    std::lock_guard lock(mu_);
    auto candidate = schedule_;
    const auto target = candidate.Next(std::max(authority,history_.confirmed_count()),next_,clock_());
    if (target) {
      const auto [input,fresh] = history_.ForFrame(*target,std::forward<Sample>(sample));
      if (fresh && !std::invoke(std::forward<Send>(send),*target,input))
        throw std::runtime_error("Failed to publish timed native input");
    }
    schedule_ = candidate;
    return target;
  }
 private:
  static std::int64_t Now() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
  }
  std::mutex mu_;
  LocalInputHistory& history_;
  const Clock clock_;
  NativePublicationClock schedule_;
  frame_id_t next_=0;
};
} // namespace frame_sync
