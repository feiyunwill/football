// 2026-09-13: publish at the native cadence even when authority arrives in batches.
#pragma once
#include "frame_sync/server_input_window.hpp"
#include "frame_sync/native_match_contract.hpp"
#include <algorithm>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
namespace frame_sync {
class OriginalNativePublicationClock {
 public:
  static constexpr std::int64_t kPeriod = 1000000000LL / NativeMatchContract::kHz;
  OriginalNativePublicationClock() = default;
  ~OriginalNativePublicationClock() = default;
  OriginalNativePublicationClock(const OriginalNativePublicationClock&) = default;
  OriginalNativePublicationClock& operator=(const OriginalNativePublicationClock&) = default;
  OriginalNativePublicationClock(OriginalNativePublicationClock&&) = default;
  OriginalNativePublicationClock& operator=(OriginalNativePublicationClock&&) = default;

  std::optional<frame_id_t> Next(frame_id_t authority, frame_id_t simulation, std::int64_t now) {
    if (now < 0 || (observed_ && now < observed_time_))
      throw std::invalid_argument("Native publication clock moved backwards");
    if (now > std::numeric_limits<std::int64_t>::max() - kPeriod)
      throw std::overflow_error("Native publication time exhausted");
    const auto known = std::max(authority_, authority);
    const auto floor = std::max(std::uint64_t(known) + 1, std::uint64_t(simulation));
    const auto ceiling = std::min(std::uint64_t(known) + ServerInputWindow::kFrames - 1,
                                  std::uint64_t(UINT32_MAX) - 1);
    if (floor >= UINT32_MAX) throw std::overflow_error("Native publication frame exhausted");
    // 2026-09-13: fresh authority corrects speculative wall-clock lead after slow
    // authority work. Existing future publications remain immutable while it catches up.
    if (published_ && known > authority_ && floor <= last_frame_)
      deadline_ = now + kPeriod;
    authority_ = known; observed_ = true; observed_time_ = now;
    // Do not consume device edges if prediction or a stalled authority leaves no slot.
    if (floor > ceiling) return std::nullopt;
    if (!published_ || floor > last_frame_) {
      last_frame_ = static_cast<frame_id_t>(floor);
      published_ = true; deadline_ = now + kPeriod;
      return last_frame_;
    }
    if (now < deadline_ || last_frame_ >= ceiling) return std::nullopt;
    // Expired local publication opportunities cannot be filled with newly observed
    // input. Send only the current opportunity; the authority owns missing old slots.
    const auto count = std::uint64_t(1 + (now - deadline_) / kPeriod);
    last_frame_ = static_cast<frame_id_t>(std::min(std::uint64_t(last_frame_) + count, ceiling));
    deadline_ = now + kPeriod - (now - deadline_) % kPeriod;
    return last_frame_;
  }
 private:
  frame_id_t authority_ = 0, last_frame_ = 0;
  std::int64_t observed_time_ = 0, deadline_ = 0;
  bool observed_ = false, published_ = false;
};
} // namespace frame_sync
