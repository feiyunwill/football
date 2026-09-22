// 2026-09-13: shared native deadlines and SDL input ownership.
#pragma once
#include "frame_sync/native_ui_owner.hpp"
#include "frame_sync/native_shared_timeline.hpp"
#include <algorithm>
#include <array>
#include <mutex>
// 2026-09-13: window sampling and transport admission share serialized input state.
// #include "frame_sync/native_input_buffer.hpp"
#include "frame_sync/native_input_buffer.hpp"
#include "frame_sync/native_shared_input.hpp"
// 2026-09-14: external game/GL worker explicitly releases its SDL thread-local allocations.
#include "frame_sync/native_sdl_thread_state.hpp"
#include "game_env.hpp"
#include "main.hpp"
#include <chrono>
#include <limits>
// 2026-09-13: sample UI input at bounded render work opportunities.
// #include <thread>
#include <thread>
#include "systems/graphics/render_service.hpp"
// 2026-09-13: bind sampled input to fixed simulation deadlines.
// #include <utility>
#include <utility>
#include <memory>
#include "frame_sync/native_input_timeline.hpp"

namespace frame_sync {
inline std::int64_t NativeNow() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
// Absolute opportunities; late work never skips simulation frame IDs.
class NativeLoopClock {
 public:
  NativeLoopClock(std::int64_t now, int logic_hz, int render_hz)
      : logic_period_(Period(logic_hz)), render_period_(Period(render_hz)),
        poll_next_(now), logic_next_(now), render_next_(now), last_(now) {
    if (now < 0) throw std::invalid_argument("Invalid loop start");
  }
  ~NativeLoopClock() = default;
  NativeLoopClock(const NativeLoopClock&) = delete;
  NativeLoopClock& operator=(const NativeLoopClock&) = delete;
  NativeLoopClock(NativeLoopClock&&) = delete;
  NativeLoopClock& operator=(NativeLoopClock&&) = delete;
  bool PollDue(std::int64_t now) { return Take(now, poll_next_, 4000000); }
// 2026-09-13: separate fixed simulation debt from skippable wall-clock publication opportunities.
//   bool LogicDue(std::int64_t now) { return Take(now, logic_next_, logic_period_); }
  bool LogicDue(std::int64_t now) { return Take(now, logic_next_, logic_period_); }
  // Fixed simulation time retains every overdue tick. The owner bounds work per
  // turn and polls input again before continuing; rendering never consumes debt.
  bool FixedLogicDue(std::int64_t now) {
    Observe(now);
    if (now < logic_next_) return false;
    if (logic_next_ > std::numeric_limits<std::int64_t>::max() - logic_period_)
      throw std::overflow_error("Native fixed simulation clock exhausted");
// 2026-09-13: bind sampled input to fixed simulation deadlines.
//     logic_next_ += logic_period_;
    last_fixed_ = logic_next_;
    logic_next_ += logic_period_;
    return true;
  }
  bool LogicPending(std::int64_t now) {
    Observe(now);
    return now >= logic_next_;
  }
  bool RenderDue(std::int64_t now) { return Take(now, render_next_, render_period_); }
// 2026-09-13: bind sampled input to fixed simulation deadlines.
//   void RestartLogic(std::int64_t now) { Observe(now); logic_next_ = now; }
  std::int64_t LastFixedDeadline() const {
    if (last_fixed_ < 0) throw std::logic_error("No fixed deadline has been consumed");
    return last_fixed_;
  }
  void RestartLogic(std::int64_t now) { Observe(now); logic_next_ = now; last_fixed_ = -1; }
  std::int64_t Next(bool logic, bool render) const {
    auto next = poll_next_;
    if (logic) next = std::min(next, logic_next_);
    if (render) next = std::min(next, render_next_);
    return next;
  }
  void Wait(bool logic, bool render) const {
    std::this_thread::sleep_until(std::chrono::steady_clock::time_point(
        std::chrono::duration_cast<std::chrono::steady_clock::duration>(
            std::chrono::nanoseconds(Next(logic, render)))));
  }
  static std::int64_t Period(int hz) {
    if (hz < 1 || hz > 1000) throw std::invalid_argument("Invalid native frame rate");
    return 1000000000LL / hz;
  }
 private:
  void Observe(std::int64_t now) {
    if (now < last_) throw std::invalid_argument("Loop clock moved backwards");
    last_ = now;
  }
  bool Take(std::int64_t now, std::int64_t& next, std::int64_t period) {
    Observe(now);
    if (now < next) return false;
    const auto remainder = (now - next) % period;
    const auto advance = period - remainder;
    if (now > std::numeric_limits<std::int64_t>::max() - advance)
      throw std::overflow_error("Native loop clock exhausted");
    next = now + advance;
    return true;
  }
  const std::int64_t logic_period_, render_period_;
// 2026-09-13: bind sampled input to fixed simulation deadlines.
//   std::int64_t poll_next_, logic_next_, render_next_, last_;
  std::int64_t poll_next_, logic_next_, render_next_, last_;
  std::int64_t last_fixed_ = -1;
};
// 2026-09-13: keep SDL on its creating thread; the joined game worker owns simulation and GL.
// class NativeWindowInput {
//  public:
//   explicit NativeWindowInput(GameEnv& env) : env_(env) {}
//   ~NativeWindowInput() = default;
//   NativeWindowInput(const NativeWindowInput&) = delete;
//   NativeWindowInput& operator=(const NativeWindowInput&) = delete;
//   NativeWindowInput(NativeWindowInput&&) = delete;
//   NativeWindowInput& operator=(NativeWindowInput&&) = delete;
//   void Poll(bool standalone = false) {
//     if (!env_.game_config.render) return;
//     ContextHolder selected(&env_);
//     auto sample = sampler_.poll(SDL_GL_GetCurrentWindow());
//     if (standalone) {
//       // Preserve standalone Escape-to-pause; Q/window close still quit.
//       for (auto* names : {&sample.keys, &sample.pressed_keys})
//         for (auto& name : *names) if (name == "escape") name = "k";
//     }
// // 2026-09-13: bind sampled input to fixed simulation deadlines.
// //     buffer_.Feed(sample);
//     if (standalone) local_input().Feed(sample, NativeNow());
//     else buffer_.Feed(sample);
//   }
// // 2026-09-13: expose shared sampled state; device polling remains on this owner.
// //   NativeInputBuffer& buffer() { return buffer_; }
// // 2026-09-13: bind sampled input to fixed simulation deadlines.
// //   NativeSharedInputBuffer& buffer() { return buffer_; }
//   NativeSharedInputBuffer& buffer() { return buffer_; }
//   NativeInputTimeline& local_input() {
//     if (!local_) local_ = std::make_unique<NativeInputTimeline>();
//     return *local_;
//   }
// // 2026-09-13: sample UI input at bounded render work opportunities.
// //   void Title(const char* title) {
//   template<class Function> void Render(Function&& render, bool standalone = false) {
//     std::pair<NativeWindowInput*, bool> context{this, standalone};
//     blunted::ScopedRenderService service([](void* opaque) {
//       auto& value = *static_cast<std::pair<NativeWindowInput*, bool>*>(opaque);
//       value.first->Poll(value.second);
//     }, &context);
//     blunted::ScopedRenderService::Poll();
//     std::forward<Function>(render)();
//     blunted::ScopedRenderService::Poll();
//   }
//   void Title(const char* title) {
//     if (!env_.game_config.render) return;
//     ContextHolder selected(&env_);
//     if (auto* window = SDL_GL_GetCurrentWindow()) SDL_SetWindowTitle(window, title);
//   }
//  private:
//   GameEnv& env_;
//   PythonWindowInput sampler_;
// // 2026-09-13: keep SDL-independent input storage synchronized with publication.
// //   NativeInputBuffer buffer_;
// // 2026-09-13: bind sampled input to fixed simulation deadlines.
// //   NativeSharedInputBuffer buffer_;
//   NativeSharedInputBuffer buffer_;
//   std::unique_ptr<NativeInputTimeline> local_;
// };
class NativeWindowInput {
 public:
  explicit NativeWindowInput(GameEnv& env, bool standalone = false)
      // 2026-09-13: keep the expected context identity for checked worker selection.
      // : render_(env.game_config.render), standalone_(standalone) {
      : env_(env), render_(env.game_config.render), standalone_(standalone) {
    if (standalone_) local_ = std::make_unique<NativeSharedInputTimeline>();
    if (render_) {
      // Select only during setup, on the SDL creating thread. Poll never needs
      // the GameEnv mutex or moves the worker's current GL context.
      ContextHolder selected(&env);
      window_ = SDL_GL_GetCurrentWindow();
      // 2026-09-13: reject failed or incomplete graphical setup before launching work.
      // if (!window_) throw std::runtime_error("Native graphical session requires an SDL window");
      context_ = SDL_GL_GetCurrentContext();
      if (!window_ || !context_)
        throw std::runtime_error("Native graphical session requires an SDL window and context");
    }
  }
  ~NativeWindowInput() = default;
  NativeWindowInput(const NativeWindowInput&) = delete;
  NativeWindowInput& operator=(const NativeWindowInput&) = delete;
  NativeWindowInput(NativeWindowInput&&) = delete;
  NativeWindowInput& operator=(NativeWindowInput&&) = delete;

  void Poll() {
    if (!render_) return;
    if (!owner_.IsOwnerThread()) {
      owner_.CheckWorker();  // Safe cancellation boundary; never poll SDL here.
      return;
    }
    auto sample = sampler_.poll(window_);
    if (standalone_) {
      for (auto* names : {&sample.keys, &sample.pressed_keys})
        for (auto& name : *names) if (name == "escape") name = "k";
      local_->Feed(sample);
    } else buffer_.Feed(sample);
  }
  NativeSharedInputBuffer& buffer() { return buffer_; }
  NativeSharedInputTimeline& local_input() {
    if (!local_) throw std::logic_error("This native session has no local input timeline");
    return *local_;
  }
  template<class Function> void Render(Function&& render) {
    owner_.CheckWorker();
    // 2026-09-13: fail explicitly if the GL context cannot be selected on this worker.
    ContextHolder selected(&env_);
    CheckContext();
    std::forward<Function>(render)();
  }
  void Title(const char* title) {
    if (!render_) return;
    if (!owner_.IsOwnerThread()) owner_.CheckWorker();
    if (!title) throw std::invalid_argument("Native title is null");
    size_t size = 0;
    while (size < title_.size() && title[size]) ++size;
    if (size == title_.size()) throw std::length_error("Native title exceeds its fixed storage");
    std::lock_guard lock(title_mutex_);
    std::copy_n(title, size + 1, title_.begin());
    title_pending_ = true;
  }
  template<class Function> void Run(Function&& work) {
    if (!render_) { std::forward<Function>(work)(); return; }
    // 2026-09-13: verify the initial handoff without holding the environment lock across work.
    // owner_.Run(std::forward<Function>(work), [this] {
    // 2026-09-14: retain cleanup across normal exit and worker exceptions.
    // owner_.Run([&] {
    //   { ContextHolder selected(&env_); CheckContext(); }
    owner_.Run([&] {
      NativeSDLThreadState sdl_thread_state;
      { ContextHolder selected(&env_); CheckContext(); }
      std::forward<Function>(work)();
    }, [this] {
      Poll();
      std::lock_guard lock(title_mutex_);
      if (title_pending_) {
        SDL_SetWindowTitle(window_, title_.data());
        title_pending_ = false;
      }
    });
  }
 private:
  void CheckContext() const {
    if (SDL_GL_GetCurrentWindow() != window_ || SDL_GL_GetCurrentContext() != context_)
      throw std::runtime_error("Native game worker could not select its SDL GL context");
  }
  GameEnv& env_;
  const bool render_, standalone_;
  SDL_Window* window_ = nullptr;
  SDL_GLContext context_ = nullptr;
  NativeUIOwner owner_;
  PythonWindowInput sampler_;
  NativeSharedInputBuffer buffer_;
  std::unique_ptr<NativeSharedInputTimeline> local_;
  std::mutex title_mutex_;
  std::array<char, 256> title_{};
  bool title_pending_ = false;
};
}  // namespace frame_sync
