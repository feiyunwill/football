// Copyright 2026 Google LLC & Contributors
// 2026-09-09: limits on retained payload capacity, with separate object counts.
#ifndef GFOOTBALL_FRAME_SYNC_MEMORY_BUDGET_HPP
#define GFOOTBALL_FRAME_SYNC_MEMORY_BUDGET_HPP

#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace frame_sync {
inline constexpr size_t kMaxControlledSlots = 22;
inline constexpr size_t kMaxBufferedAuthorityFrames = 1024;
inline constexpr size_t kMaxBufferedInputBytes = 512 * 1024;
inline constexpr size_t kMaxSnapshotHistoryFrames = 1024;

inline size_t CheckedControlledSlots(size_t slots) {
  if (slots == 0 || slots > kMaxControlledSlots)
    throw std::invalid_argument("Controlled slot count must be in [1, 22]");
  return slots;
}

template<class T>
size_t RetainedBytes(const std::vector<T>& values) {
  if (values.capacity() > std::numeric_limits<size_t>::max() / sizeof(T))
    throw std::length_error("Vector capacity byte count overflows");
  return values.capacity() * sizeof(T);
}

// 2026-09-09: preallocate a fixed receive capacity once, then append only within
// it. Rejection leaves the old bytes intact so the owner can end the session.
inline bool AppendBoundedBytes(std::vector<uint8_t>& buffer, const uint8_t* data,
                               size_t length, size_t limit) {
  if (limit == 0 || limit > 16 * 1024 * 1024 || buffer.size() > limit ||
      buffer.capacity() > limit || length > limit - buffer.size() ||
      (length && !data)) return false;
  if (!length) return true;
  if (buffer.capacity() < limit) {
    std::vector<uint8_t> owned;
    owned.reserve(limit);
    if (owned.capacity() > limit) return false;
    owned.insert(owned.end(), buffer.begin(), buffer.end());
    buffer.swap(owned);
  }
  buffer.insert(buffer.end(), data, data + length);
  return true;
}

struct SnapshotBudget {
  // Real current 11v11 snapshots are about 90 KiB. Keep headroom without
  // allowing an opaque callback's arbitrary capacity to accumulate in history.
  explicit SnapshotBudget(size_t snapshot = 1024 * 1024,
                          size_t history = 8 * 1024 * 1024)
      : snapshot_bytes(snapshot), history_bytes(history) {
    if (snapshot == 0 || snapshot > 64 * 1024 * 1024 ||
        history < snapshot || history > 256 * 1024 * 1024)
      throw std::invalid_argument("Invalid snapshot/history byte budget");
  }
  ~SnapshotBudget() = default;
  SnapshotBudget(const SnapshotBudget&) = default;
  SnapshotBudget& operator=(const SnapshotBudget&) = default;
  SnapshotBudget(SnapshotBudget&&) = default;
  SnapshotBudget& operator=(SnapshotBudget&&) = default;

  size_t snapshot_bytes;
  size_t history_bytes;
};

struct ReplayBudget {
  explicit ReplayBudget(size_t frames = 100000, size_t bytes = 32 * 1024 * 1024)
      : frame_limit(frames), byte_limit(bytes) {
    if (frames == 0 || frames > 100000 || bytes < 128 || bytes > 64 * 1024 * 1024)
      throw std::invalid_argument("Invalid replay frame/byte budget");
  }
  ~ReplayBudget() = default;
  ReplayBudget(const ReplayBudget&) = default;
  ReplayBudget& operator=(const ReplayBudget&) = default;
  ReplayBudget(ReplayBudget&&) = default;
  ReplayBudget& operator=(ReplayBudget&&) = default;
  size_t frame_limit;
  size_t byte_limit;
};

struct DatagramBudget {
  explicit DatagramBudget(size_t packets = 256, size_t bytes = 256 * 1024)
      : packet_limit(packets), byte_limit(bytes) {
    if (packets == 0 || packets > 1024 || bytes == 0 || bytes > 16 * 1024 * 1024)
      throw std::invalid_argument("Invalid datagram packet/byte budget");
  }
  ~DatagramBudget() = default;
  DatagramBudget(const DatagramBudget&) = default;
  DatagramBudget& operator=(const DatagramBudget&) = default;
  DatagramBudget(DatagramBudget&&) = default;
  DatagramBudget& operator=(DatagramBudget&&) = default;
  size_t packet_limit;
  size_t byte_limit;
};

struct StreamBudget {
  explicit StreamBudget(size_t messages = 256, size_t bytes = 2 * 1024 * 1024)
      : message_limit(messages), byte_limit(bytes) {
    if (messages == 0 || messages > 1024 || bytes == 0 || bytes > 64 * 1024 * 1024)
      throw std::invalid_argument("Invalid TCP message/byte budget");
  }
  ~StreamBudget() = default;
  StreamBudget(const StreamBudget&) = default;
  StreamBudget& operator=(const StreamBudget&) = default;
  StreamBudget(StreamBudget&&) = default;
  StreamBudget& operator=(StreamBudget&&) = default;
  size_t message_limit;
  size_t byte_limit;
};
}  // namespace frame_sync
#endif
