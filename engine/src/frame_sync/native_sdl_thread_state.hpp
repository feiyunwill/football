// 2026-09-14: SDL TLS belongs to the external native thread that calls SDL.
#pragma once
#include <SDL_thread.h>
namespace frame_sync {
class NativeSDLThreadState {
 public:
  NativeSDLThreadState() = default;
  ~NativeSDLThreadState() noexcept { SDL_TLSCleanup(); }
  NativeSDLThreadState(const NativeSDLThreadState&) = delete;
  NativeSDLThreadState& operator=(const NativeSDLThreadState&) = delete;
  NativeSDLThreadState(NativeSDLThreadState&&) = delete;
  NativeSDLThreadState& operator=(NativeSDLThreadState&&) = delete;
};
}  // namespace frame_sync
