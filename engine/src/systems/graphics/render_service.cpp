// 2026-09-13: one shared-library TLS service, with lexical ownership.
#include "render_service.hpp"
#include <chrono>
#include <exception>
#include <limits>
#include <stdexcept>

namespace blunted {
thread_local ScopedRenderService* ScopedRenderService::active_ = nullptr;
std::int64_t ScopedRenderService::Now() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
ScopedRenderService::ScopedRenderService(Callback callback, void* context, Clock clock)
    : previous_(active_), callback_(callback), context_(context), clock_(clock),
      next_(0), last_(0) {
  if (!callback || !clock) throw std::invalid_argument("Render service requires callback and clock");
  next_ = last_ = clock_();
  if (last_ < 0) throw std::invalid_argument("Invalid render service clock");
  active_ = this;
}
ScopedRenderService::~ScopedRenderService() {
  if (active_ != this || dispatching_) std::terminate();
  active_ = previous_;
}
void ScopedRenderService::Poll() {
  auto* service = active_;
  if (!service || service->dispatching_) return;
  const auto now = service->clock_();
  if (now < service->last_) throw std::invalid_argument("Render service clock moved backwards");
  service->last_ = now;
  if (now < service->next_) return;
  constexpr std::int64_t period = 4000000;
  const auto advance = period - (now - service->next_) % period;
  if (now > std::numeric_limits<std::int64_t>::max() - advance)
    throw std::overflow_error("Render service clock exhausted");
  service->next_ = now + advance;
  service->dispatching_ = true;
  try { service->callback_(service->context_); }
  catch (...) { service->dispatching_ = false; throw; }
  service->dispatching_ = false;
}
}  // namespace blunted
