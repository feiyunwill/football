// 2026-09-13: serialize sampled input only; SDL remains on its window owner.
#pragma once
#include "frame_sync/native_input_buffer.hpp"
#include <mutex>
namespace frame_sync {
class NativeSharedInputBuffer {
 public:
  NativeSharedInputBuffer() = default;
  ~NativeSharedInputBuffer() = default;
  NativeSharedInputBuffer(const NativeSharedInputBuffer&) = delete;
  NativeSharedInputBuffer& operator=(const NativeSharedInputBuffer&) = delete;
  NativeSharedInputBuffer(NativeSharedInputBuffer&&) = delete;
  NativeSharedInputBuffer& operator=(NativeSharedInputBuffer&&) = delete;
  void Feed(const PythonWindowInput::Sample& sample) {
    std::lock_guard lock(mu_);buffer_.Feed(sample);
  }
  SlotInput Take() { std::lock_guard lock(mu_);return buffer_.Take(); }
  void SetSuspended(bool value,bool reset=false) {
    std::lock_guard lock(mu_);buffer_.SetSuspended(value,reset);
  }
  std::array<bool,3> TakeCommands() { std::lock_guard lock(mu_);return buffer_.TakeCommands(); }
  bool release_required() const { std::lock_guard lock(mu_);return buffer_.release_required(); }
  bool quit_requested() const { std::lock_guard lock(mu_);return buffer_.quit_requested(); }
  void Close() { std::lock_guard lock(mu_);buffer_.Close(); }
 private:
  mutable std::mutex mu_;
  NativeInputBuffer buffer_;
};
} // namespace frame_sync
