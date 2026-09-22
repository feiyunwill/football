// 2026-09-13: staged native presentation owner; no canonical integration yet.
#pragma once
#include "frame_sync/engine_integration.hpp"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <thread>
#include <utility>

namespace frame_sync {
// The environment supplies save_render_state(bool) and render_interpolated(float).
// Explicit monotonic timestamps let the same state machine be checked without
// sleeping. Rendering is owned here; callers must not swap the window again.
template<class Environment>
class NativePresentation {
 public:
  NativePresentation(Environment& environment, bool enabled,
                     std::chrono::nanoseconds period)
      : environment_(environment), enabled_(enabled), period_ns_(period.count()) {
    if (period_ns_ <= 0 || period_ns_ > 1000000000)
      throw std::invalid_argument("Invalid presentation logic period");
  }
  ~NativePresentation() = default;
  NativePresentation(const NativePresentation&) = delete;
  NativePresentation& operator=(const NativePresentation&) = delete;
  NativePresentation(NativePresentation&&) = delete;
  NativePresentation& operator=(NativePresentation&&) = delete;

  void Initialize(std::int64_t now) {
    Owner();
    if (initialized_) throw std::logic_error("Presentation already initialized");
    Observe(now);
    if (enabled_) environment_.save_render_state(false);
    initialized_ = true;
  }

  void BeginTick(std::int64_t now) {
    Owner();
    if (tick_active_) throw std::logic_error("Presentation tick is already active");
    if (paused_) throw std::logic_error("Paused presentation cannot advance logic");
    Ready(now);
    tick_active_ = true;
    dirty_ = false;
    captured_display_ = false;
    // A new logical target arriving during an unfinished correction must not
    // jump back to an undisplayed physical endpoint.
    preserve_display_ = correction_active_ && blend_start_ &&
                        now - *blend_start_ < period_ns_;
  }

  void BeforeStep() {
    Owner();
    if (!tick_active_) throw std::logic_error("Step outside presentation tick");
    if (enabled_) {
      if (preserve_display_ && presented_) CaptureDisplay();
      else environment_.save_render_state(false);
    }
    // Consecutive catchup steps capture each preceding physics endpoint,
    // leaving the final coherent pair without replaying intermediate images.
    dirty_ = true;
  }

  void BeforeRestore() {
    Owner();
    if (!tick_active_) throw std::logic_error("Restore outside presentation tick");
    preserve_display_ = presented_;
    if (enabled_) {
      if (presented_) CaptureDisplay();
      else environment_.save_render_state(false);
    }
    dirty_ = true;
  }

  bool CommitTick(std::int64_t now) {
    Owner();
    if (!tick_active_) throw std::logic_error("No presentation tick to commit");
    Ready(now);
    tick_active_ = false;
    if (!dirty_) return false;  // waiting is not a new publication
    blend_start_ = now;
    correction_active_ = preserve_display_;
    return true;
  }

  void Pause(std::int64_t now) {
    Owner();
    if (tick_active_) throw std::logic_error("Cannot pause a partial presentation tick");
    Ready(now);
    if (paused_) return;
    if (enabled_ && presented_) environment_.save_render_state(true);
    paused_ = true;
  }

  void Resume(std::int64_t now) {
    Owner();
    if (tick_active_) throw std::logic_error("Cannot resume a partial presentation tick");
    Ready(now);
    if (!paused_) return;
    paused_ = false;
    if (presented_) {
      blend_start_ = now;
      correction_active_ = true;
    }
  }

  bool Render(std::int64_t now) {
    Owner();
    if (tick_active_) throw std::logic_error("Cannot present a partial logical tick");
    Ready(now);
    if (!enabled_) return false;
    const float alpha = !presented_ ? 1.f : paused_ ? 0.f : !blend_start_ ? 1.f :
        static_cast<float>(std::min(1., double(now - *blend_start_) / double(period_ns_)));
    environment_.render_interpolated(alpha);
    presented_ = true;
    if (!paused_ && alpha == 1.f) {
      blend_start_.reset();
      correction_active_ = false;
    }
    return true;
  }

  EngineCallbacks Wrap(EngineCallbacks callbacks) {
    Owner();
    if (!enabled_) return callbacks;
    if (!callbacks.step_frame || !callbacks.restore_state)
      throw std::invalid_argument("Presentation needs complete engine mutation callbacks");
    auto step = std::move(callbacks.step_frame);
    auto restore = std::move(callbacks.restore_state);
    callbacks.step_frame = [this, step = std::move(step)](std::span<const SlotInput> inputs) {
      BeforeStep();
      step(inputs);
    };
    callbacks.restore_state = [this, restore = std::move(restore)](const StateBlob& state) {
      BeforeRestore();
      restore(state);
    };
    // The single-slot callback must use the same mutation boundary as step_frame.
    if (callbacks.step) {
      auto single = std::move(callbacks.step);
      callbacks.step = [this, single = std::move(single)](const SlotInput& input) {
        BeforeStep();
        single(input);
      };
    }
    return callbacks;
  }

 private:
  void Owner() const {
    if (std::this_thread::get_id() != owner_)
      throw std::logic_error("Presentation belongs to its creating thread");
  }
  void Observe(std::int64_t now) {
    Owner();
    if (now < 0 || (last_observed_ && now < *last_observed_))
      throw std::invalid_argument("Presentation clock is invalid or moved backwards");
    last_observed_ = now;
  }
  void Ready(std::int64_t now) {
    Owner();
    if (!initialized_) throw std::logic_error("Presentation is not initialized");
    Observe(now);
  }
  void CaptureDisplay() {
    if (!captured_display_) {
      environment_.save_render_state(true);
      captured_display_ = true;
    }
  }

  Environment& environment_;
  const bool enabled_;
  const std::int64_t period_ns_;
  const std::thread::id owner_ = std::this_thread::get_id();
  std::optional<std::int64_t> last_observed_, blend_start_;
  bool initialized_ = false, presented_ = false, paused_ = false;
  bool tick_active_ = false, dirty_ = false;
  bool preserve_display_ = false, captured_display_ = false, correction_active_ = false;
};
}  // namespace frame_sync
