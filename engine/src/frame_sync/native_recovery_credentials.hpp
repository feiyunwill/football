// 2026-09-14: bounded credential/ownership state for native recovery.
// Caller serializes this table with session ownership. It does not step GameEnv,
// choose inputs, or authenticate/encrypt the network transport.
#pragma once
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include <stdexcept>
#if defined(__linux__)
#include <sys/random.h>
#endif
namespace frame_sync {
using NativeRecoverySecret = std::array<uint8_t, 32>;
using NativeRecoveryMatchId = std::array<uint8_t, 16>;
inline void clear_native_secret(std::span<uint8_t> bytes) noexcept {
  volatile uint8_t* at = bytes.data();
  for (size_t i = 0; i < bytes.size(); ++i) at[i] = 0;
}
inline bool native_entropy(std::span<uint8_t> bytes) noexcept {
  // Single bounded OS request. Fail closed if entropy is unavailable; never use
  // the deterministic match seed, a counter, or an insecure fallback.
  // 2026-09-14: bound work before touching the caller buffer.
  // clear_native_secret(bytes);
  if (bytes.empty() || bytes.size() > 32) return false;
  clear_native_secret(bytes);
#if defined(__linux__)
  const auto received = ::getrandom(bytes.data(), bytes.size(), GRND_NONBLOCK);
  if (received == static_cast<ssize_t>(bytes.size())) return true;
#endif
  clear_native_secret(bytes);
  return false;
}
template <size_t N>
inline bool native_secret_equal(const std::array<uint8_t, N>& a,
                                const std::array<uint8_t, N>& b) noexcept {
  // Scan the complete fixed-size secret without an early mismatch return.
  volatile unsigned difference = 0;
  for (size_t i = 0; i < N; ++i) difference = difference | (a[i] ^ b[i]);
  return difference == 0;
}
struct NativeRecoveryGrant {
  NativeRecoveryMatchId match{};
  NativeRecoverySecret secret{};
  uint16_t slot = 22;
  uint64_t generation = 0;
  NativeRecoveryGrant() = default;
  ~NativeRecoveryGrant() = default;
  NativeRecoveryGrant(const NativeRecoveryGrant&) = default;
  NativeRecoveryGrant& operator=(const NativeRecoveryGrant&) = default;
  NativeRecoveryGrant(NativeRecoveryGrant&&) = default;
  NativeRecoveryGrant& operator=(NativeRecoveryGrant&&) = default;
};
class NativeRecoveryCredentials {
 public:
  using Time = std::chrono::steady_clock::time_point;
  using Entropy = bool (*)(std::span<uint8_t>) noexcept;
  static constexpr size_t kMaxSlots = 22;
  NativeRecoveryCredentials() = delete;
  explicit NativeRecoveryCredentials(size_t slots,
      std::chrono::milliseconds grace = std::chrono::seconds(30),
      Entropy entropy = native_entropy)
      : slots_(slots), grace_(grace), entropy_(entropy) {
    if (!slots || slots > kMaxSlots || grace.count() < 1 ||
        grace > std::chrono::minutes(5) || !entropy)
      throw std::invalid_argument("Invalid native recovery limits");
    for (unsigned attempt = 0; attempt < 4; ++attempt) {
      if (!entropy_(match_)) break;
      if (!zero(match_)) return;
    }
    throw std::runtime_error("Native recovery entropy unavailable");
  }
  ~NativeRecoveryCredentials() {
    for (auto& cell : cells_) {
      clear_native_secret(cell.current);
      clear_native_secret(cell.pending);
    }
  }
  NativeRecoveryCredentials(const NativeRecoveryCredentials&) = delete;
  NativeRecoveryCredentials& operator=(const NativeRecoveryCredentials&) = delete;
  NativeRecoveryCredentials(NativeRecoveryCredentials&&) = delete;
  NativeRecoveryCredentials& operator=(NativeRecoveryCredentials&&) = delete;
  const NativeRecoveryMatchId& match_id() const { return match_; }

  // Initial admission is separate from native Ready/engine initialization.
  std::optional<NativeRecoveryGrant> issue(uint16_t slot, Time now) {
    // 2026-09-14: check physical array bounds explicitly as well as configured slots.
    // if (!advance(now) || slot >= slots_ || !next_generation_ ||
    // 2026-09-14: the match owner seals fresh admission at the first authority frame.
    // if (!advance(now) || slot >= kMaxSlots || slot >= slots_ || !next_generation_ ||
    //     cells_[slot].phase != Phase::Empty) return std::nullopt;
    if (!advance(now) || admissions_sealed_ || slot >= kMaxSlots ||
        slot >= slots_ || !next_generation_ ||
        cells_[slot].phase != Phase::Empty) return std::nullopt;
    NativeRecoverySecret fresh{};
    if (!fresh_secret(fresh)) return std::nullopt;
    auto& cell = cells_[slot];
    cell.current = fresh;
    cell.generation = next_generation_++;
    cell.phase = Phase::Attached;
    return grant(slot, cell.current);
  }
  // Only the authoritative match lifecycle may close initial admission.
  // There is no operation to reopen it during this match.
  void seal_admissions() { admissions_sealed_ = true; }
  bool release_admission(uint16_t slot, uint64_t generation, Time now) {
    if (!advance(now) || admissions_sealed_ || slot >= kMaxSlots ||
        slot >= slots_ || generation == 0) return false;
    auto& cell = cells_[slot];
    if (cell.phase == Phase::Empty || cell.generation != generation) return false;
    // Pregame timeout cleanup may arrive after the detached lease expired.
    // Preserve the match identity and monotonic generation sequence.
    expire(cell);
    cell = Cell{};
    return true;
  }
  bool detach(uint16_t slot, uint64_t generation, Time now) {
    // 2026-09-14: check physical array bounds explicitly as well as configured slots.
    // if (!advance(now) || slot >= slots_) return false;
    if (!advance(now) || slot >= kMaxSlots || slot >= slots_) return false;
    auto& cell = cells_[slot];
    if (cell.generation != generation || !live(cell)) return false;
    if (cell.phase == Phase::Attached) {
      if (Time::max() - now < grace_) return false;
      cell.deadline = now + grace_;
    }
    // An aborted restore or duplicate close keeps its ORIGINAL grace deadline.
    cell.phase = Phase::Detached;
    return true;
  }
  std::optional<NativeRecoveryGrant> begin(
      uint16_t slot, const NativeRecoveryMatchId& match,
      const NativeRecoverySecret& secret, Time now) {
    // 2026-09-14: check physical array bounds explicitly as well as configured slots.
    // if (!advance(now) || slot >= slots_ || !next_generation_ ||
    if (!advance(now) || slot >= kMaxSlots || slot >= slots_ || !next_generation_ ||
        !native_secret_equal(match, match_)) return std::nullopt;
    auto& cell = cells_[slot];
    if (!live(cell) || zero(secret)) return std::nullopt;
    const bool current = native_secret_equal(secret, cell.current);
    const bool pending = native_secret_equal(secret, cell.pending);
    if (!(current | pending)) return std::nullopt;
    if (cell.phase == Phase::Attached && Time::max() - now < grace_)
      return std::nullopt;
    NativeRecoverySecret next = cell.pending;
    if (zero(next) && !fresh_secret(next)) return std::nullopt;
    if (cell.phase == Phase::Attached) cell.deadline = now + grace_;
    // Retain the same pending secret across retries. Both old and pending
    // credentials survive a lost response until Ready proves receipt.
    cell.pending = next;
    cell.phase = Phase::Claimed;
    cell.generation = next_generation_++;
    return grant(slot, cell.pending);
  }
  bool commit(uint16_t slot, uint64_t generation,
              const NativeRecoverySecret& received_secret, Time now) {
    // 2026-09-14: check physical array bounds explicitly as well as configured slots.
    // if (!advance(now) || slot >= slots_) return false;
    if (!advance(now) || slot >= kMaxSlots || slot >= slots_) return false;
    auto& cell = cells_[slot];
    // 2026-09-14: a lost Ready acknowledgement may repeat the same proof.
    // Previously only Phase::Claimed could commit.
    if (cell.phase == Phase::Attached)
      return cell.generation == generation &&
          native_secret_equal(received_secret, cell.current);
    if (cell.phase != Phase::Claimed || cell.generation != generation ||
        !native_secret_equal(received_secret, cell.pending)) return false;
    cell.current = cell.pending;
    clear_native_secret(cell.pending);
    cell.phase = Phase::Attached;
    cell.deadline = Time{};
    return true;
  }
  bool owns(uint16_t slot, uint64_t generation, Time now) {
    // 2026-09-14: check physical array bounds explicitly as well as configured slots.
    // if (!advance(now) || slot >= slots_) return false;
    if (!advance(now) || slot >= kMaxSlots || slot >= slots_) return false;
    const auto& cell = cells_[slot];
    return cell.generation == generation &&
        (cell.phase == Phase::Attached || cell.phase == Phase::Claimed);
  }
  bool attached(uint16_t slot, uint64_t generation, Time now) {
    return owns(slot, generation, now) && cells_[slot].phase == Phase::Attached;
  }
  bool revoke(uint16_t slot, uint64_t generation, Time now) {
    // 2026-09-14: check physical array bounds explicitly as well as configured slots.
    // if (!advance(now) || slot >= slots_ || !live(cells_[slot]) ||
    if (!advance(now) || slot >= kMaxSlots || slot >= slots_ || !live(cells_[slot]) ||
        cells_[slot].generation != generation) return false;
    expire(cells_[slot]);
    return true;
  }

 private:
  enum class Phase { Empty, Attached, Detached, Claimed, Expired };
  struct Cell {
    NativeRecoverySecret current{}, pending{};
    Time deadline{};
    uint64_t generation = 0;
    Phase phase = Phase::Empty;
    Cell() = default;
    ~Cell() = default;
    Cell(const Cell&) = default;
    Cell& operator=(const Cell&) = default;
    Cell(Cell&&) = default;
    Cell& operator=(Cell&&) = default;
  };
  static bool live(const Cell& cell) {
    return cell.phase != Phase::Empty && cell.phase != Phase::Expired;
  }
  template <size_t N>
  static bool zero(const std::array<uint8_t, N>& bytes) {
    unsigned bits = 0;
    for (const auto value : bytes) bits |= value;
    return bits == 0;
  }
  static void expire(Cell& cell) {
    clear_native_secret(cell.current);
    clear_native_secret(cell.pending);
    cell.phase = Phase::Expired;
  }
  bool advance(Time now) {
    if (now < Time{} || now < last_time_) return false;
    last_time_ = now;
    for (auto& cell : cells_)
      if ((cell.phase == Phase::Detached || cell.phase == Phase::Claimed) &&
          now >= cell.deadline) expire(cell);
    return true;
  }
  bool fresh_secret(NativeRecoverySecret& fresh) {
    for (unsigned attempt = 0; attempt < 4; ++attempt) {
      if (!entropy_(fresh)) break;
      if (zero(fresh)) continue;
      bool duplicate = false;
      for (const auto& cell : cells_) {
        duplicate |= native_secret_equal(fresh, cell.current);
        duplicate |= native_secret_equal(fresh, cell.pending);
      }
      if (!duplicate) return true;
    }
    clear_native_secret(fresh);
    return false;
  }
  NativeRecoveryGrant grant(uint16_t slot, const NativeRecoverySecret& secret) const {
    NativeRecoveryGrant result;
    result.match = match_;
    result.secret = secret;
    result.slot = slot;
    result.generation = cells_[slot].generation;
    return result;
  }
  const size_t slots_;
  const std::chrono::milliseconds grace_;
  const Entropy entropy_;
  NativeRecoveryMatchId match_{};
  std::array<Cell, kMaxSlots> cells_{};
  uint64_t next_generation_ = 1;
  Time last_time_{};
  bool admissions_sealed_ = false;
};
}  // namespace frame_sync
