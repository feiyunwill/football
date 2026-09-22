// 2026-09-13: cooperative UI service at renderer boundaries, on the render owner.
#pragma once
#include <cstdint>

namespace blunted {
// A scoped callback may sample devices and publish external UI state only.
// It must not draw, switch graphics contexts, step or mutate the game.
// Scopes are thread-local; dormant/headless callers never invoke a clock or SDL.
class ScopedRenderService {
 public:
  using Callback = void (*)(void*);
  using Clock = std::int64_t (*)();
  explicit ScopedRenderService(Callback callback, void* context, Clock clock = Now);
  ~ScopedRenderService();
  ScopedRenderService(const ScopedRenderService&) = delete;
  ScopedRenderService& operator=(const ScopedRenderService&) = delete;
  ScopedRenderService(ScopedRenderService&&) = delete;
  ScopedRenderService& operator=(ScopedRenderService&&) = delete;
  static void Poll();
 private:
  static std::int64_t Now();
  static thread_local ScopedRenderService* active_;
  ScopedRenderService* previous_;
  Callback callback_;
  void* context_;
  Clock clock_;
  std::int64_t next_, last_;
  bool dispatching_ = false;
};
}  // namespace blunted
