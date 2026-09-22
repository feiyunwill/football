// 2026-09-13: staged shared native input buffer; integrate after frozen performance gates.
#pragma once
#include "frame_sync/protocol.hpp"
#include "frame_sync/python_window_input.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <stdexcept>
// 2026-09-13: bind sampled input to fixed simulation deadlines.
// #include <string_view>
#include <string_view>
#include <tuple>

namespace frame_sync {
// Single UI/simulation owner. Polling records state; Take() admits one new frame.
class NativeInputBuffer {
 public:
  explicit NativeInputBuffer(double deadzone = .18) : deadzone_(deadzone) {
    if (!std::isfinite(deadzone) || deadzone < 0 || deadzone > .5)
      throw std::invalid_argument("Controller deadzone must be within 0..0.5");
  }
  ~NativeInputBuffer() = default;
  NativeInputBuffer(const NativeInputBuffer&) = delete;
  NativeInputBuffer& operator=(const NativeInputBuffer&) = delete;
  NativeInputBuffer(NativeInputBuffer&&) = delete;
  NativeInputBuffer& operator=(NativeInputBuffer&&) = delete;

  void Feed(const PythonWindowInput::Sample& sample) {
    // Validate the whole observation before changing any retained state.
    const auto keys = KeyMask(sample.keys);
    const auto pressed = KeyMask(sample.pressed_keys);
    for (float axis : sample.axes)
      if (!std::isfinite(axis) || axis < -1 || axis > 1)
        throw std::invalid_argument("Invalid controller axis");
    if (closed_) throw std::logic_error("Input buffer is closed");
    quit_ |= sample.quit;
    if (!sample.focused) {
      keys_ = pad_ = keyboard_pending_ = pad_pending_ = 0;
      direction_ = {};
      save_ = pause_ = false;
      return;
    }
    const auto new_keys = (keys & ~keys_) | pressed;
    const auto new_pad = sample.connected
        ? static_cast<std::uint16_t>((sample.buttons & ~pad_) | sample.pressed_buttons) : 0;
    keyboard_pending_ |= Buttons(new_keys, 0);
    pad_pending_ = sample.connected ? pad_pending_ | Buttons(0, new_pad) : 0;
    quit_ |= (new_keys & (Key("q") | Key("escape"))) != 0 || (new_pad & (1u << 4));
    save_ |= (new_keys & Key("p")) != 0 || (new_pad & (1u << 6));
    pause_ ^= (new_keys & Key("k")) != 0 || (new_pad & (1u << 5));
    keys_ = keys;
    pad_ = sample.connected ? sample.buttons : 0;
    if (suspended_ || resume_neutral_) {
      keyboard_pending_ = pad_pending_ = 0;
      direction_ = {};
      // 2026-09-13: the class body is incomplete at local constexpr evaluation.
      // constexpr auto gameplay_keys = (1u << names_.size()) - 1u -
      const auto gameplay_keys = ((1u << names_.size()) - 1u) & ~
          (Key("p") | Key("q") | Key("escape") | Key("k"));
      constexpr std::uint16_t gameplay_pad = (1u << 0) | (1u << 1) | (1u << 2) |
          (1u << 3) | (1u << 7) | (1u << 8) | (1u << 9) | (1u << 10) | (15u << 11);
      const bool neutral = !((keys | pressed) & gameplay_keys) &&
          !(sample.connected && (((sample.buttons | sample.pressed_buttons) & gameplay_pad) ||
                                 std::hypot(double(sample.axes[0]), double(sample.axes[1])) > deadzone_));
      if (!suspended_ && neutral) resume_neutral_ = false;
      return;
    }
    // 2026-09-13: preserve constant folding without premature constexpr evaluation.
    // constexpr auto directions = Key("w") | ...;
    const auto directions = Key("w") | Key("a") | Key("s") | Key("d") |
        Key("up") | Key("left") | Key("down") | Key("right");
    const bool digital = keys & directions;
    double x = !!(keys & (Key("d") | Key("right"))) - !!(keys & (Key("a") | Key("left")));
    double y = !!(keys & (Key("w") | Key("up"))) - !!(keys & (Key("s") | Key("down")));
    if (!digital && sample.connected) {
      if (sample.buttons & (15u << 11)) {
        x = !!(sample.buttons & (1u << 14)) - !!(sample.buttons & (1u << 13));
        y = !!(sample.buttons & (1u << 11)) - !!(sample.buttons & (1u << 12));
      } else {
        x = sample.axes[0];
        y = sample.axes[1];
        const double length = std::hypot(x, y);
        const double scale = length > deadzone_ ? (std::min(length, 1.) - deadzone_) / (1. - deadzone_) : 0.;
        if (length) { x = x * scale / length; y = y * scale / length; }
        else { x = 0.; y = 0.; }
      }
    }
    const double length = std::hypot(x, y);
    direction_ = length > 1 ? std::array{x / length, y / length} : std::array{x, y};
  }

  SlotInput Take() {
    if (suspended_ || resume_neutral_) {
      keyboard_pending_ = pad_pending_ = 0;
      return SlotInput::Default();
    }
    const SlotInput result{static_cast<float>(direction_[0]), static_cast<float>(direction_[1]),
        static_cast<std::uint16_t>(Buttons(keys_, pad_) | keyboard_pending_ | pad_pending_)};
    keyboard_pending_ = pad_pending_ = 0;
    return result;
  }

// 2026-09-13: bind sampled input to fixed simulation deadlines.
//   void SetSuspended(bool suspended, bool reset = false) {
  // Capture held state separately from the two edge sources. The timed local
  // owner needs to cancel controller edges on disconnect without losing a
  // keyboard tap. Existing network Take() retains its original semantics.
  std::tuple<SlotInput, std::uint16_t, std::uint16_t> TakeObservation() {
    if (suspended_ || resume_neutral_) {
      keyboard_pending_ = pad_pending_ = 0;
      return {SlotInput::Default(), 0, 0};
    }
    const SlotInput held{static_cast<float>(direction_[0]), static_cast<float>(direction_[1]),
                         Buttons(keys_, pad_)};
    const auto keyboard = keyboard_pending_, pad = pad_pending_;
    keyboard_pending_ = pad_pending_ = 0;
    return {held, keyboard, pad};
  }

  void SetSuspended(bool suspended, bool reset = false) {
    if (closed_) throw std::logic_error("Input buffer is closed");
    if (suspended == suspended_ && !reset) return;
    suspended_ = suspended;
    resume_neutral_ = true;
    keyboard_pending_ = pad_pending_ = 0;
    direction_ = {};
  }

  std::array<bool, 3> TakeCommands() noexcept {
    const std::array result{quit_, save_, pause_};
    save_ = pause_ = false;
    return result;
  }

  bool release_required() const noexcept { return resume_neutral_ && !suspended_; }
  bool quit_requested() const noexcept { return quit_; }

  void Close() noexcept {
    closed_ = quit_ = true;
    keys_ = pad_ = keyboard_pending_ = pad_pending_ = 0;
    direction_ = {};
    save_ = pause_ = false;
  }

 private:
  inline static constexpr std::array<std::string_view, 24> names_ = {
      "w", "a", "s", "d", "up", "left", "down", "right", "z", "x", "c", "v",
      "r", "b", "space", "n", "tab", "lshift", "rshift", "m", "p", "q", "escape", "k"};
  static constexpr std::uint32_t Key(std::string_view name) noexcept {
    for (std::size_t i = 0; i < names_.size(); ++i)
      if (names_[i] == name) return 1u << i;
    return 0;
  }
  static std::uint32_t KeyMask(const std::vector<std::string>& names) {
    if (names.size() > names_.size()) throw std::invalid_argument("Too many keyboard names");
    std::uint32_t result = 0;
    for (const auto& name : names) {
      const auto bit = Key(name);
      if (!bit) throw std::invalid_argument("Unknown input key");
      result |= bit;
    }
    return result;
  }
  static constexpr std::uint16_t Buttons(std::uint32_t keys, std::uint16_t pad) noexcept {
    constexpr std::array<int, 12> key_actions = {2, 1, 0, 3, 4, 5, 6, 7, 8, 9, 9, 10};
    constexpr std::array<int, 15> pad_actions = {2, 3, 1, 0, -1, -1, -1, 10, 6, 8, 9, -1, -1, -1, -1};
    std::uint16_t result = 0;
    for (std::size_t i = 0; i < key_actions.size(); ++i)
      if (keys & (1u << (i + 8))) result |= 1u << key_actions[i];
    for (std::size_t i = 0; i < pad_actions.size(); ++i)
      if (pad_actions[i] >= 0 && (pad & (1u << i))) result |= 1u << pad_actions[i];
    return result;
  }
  double deadzone_;
  std::uint32_t keys_ = 0;
  std::uint16_t pad_ = 0, keyboard_pending_ = 0, pad_pending_ = 0;
  std::array<double, 2> direction_{};
  bool quit_ = false, save_ = false, pause_ = false, closed_ = false;
  bool suspended_ = false, resume_neutral_ = false;
};
}  // namespace frame_sync
