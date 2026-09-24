
// A seat group shares one recovery lease and changes ownership atomically.
// The caller uses the same serialized owner as NativeRecoveryCredentials.
#pragma once
#include "frame_sync/native_recovery_credentials.hpp"
#include <bit>
namespace frame_sync {
struct NativeRecoveryGroupGrant {
  NativeRecoveryGrant lease;
  uint32_t slots = 0;
};
class NativeRecoveryGroups {
 public:
  using Time = NativeRecoveryCredentials::Time;
  using Entropy = NativeRecoveryCredentials::Entropy;
  static constexpr uint32_t kAllSlots = (uint32_t{1} << NativeRecoveryCredentials::kMaxSlots) - 1;
  explicit NativeRecoveryGroups(size_t slots,
      std::chrono::milliseconds grace = std::chrono::seconds(30),
      Entropy entropy = native_entropy)
      : credentials_(slots, grace, entropy),
        valid_slots_((uint32_t{1} << slots) - 1) {}
  NativeRecoveryGroups(const NativeRecoveryGroups&) = delete;
  NativeRecoveryGroups& operator=(const NativeRecoveryGroups&) = delete;
  NativeRecoveryGroups(NativeRecoveryGroups&&) = delete;
  NativeRecoveryGroups& operator=(NativeRecoveryGroups&&) = delete;
  const NativeRecoveryMatchId& match_id() const { return credentials_.match_id(); }
  void seal_admissions() { credentials_.seal_admissions(); }

  // The mask is chosen by the authoritative roster allocator, never by a peer.
  // Failed entropy or lease admission leaves every candidate seat unreserved.
  std::optional<NativeRecoveryGroupGrant> issue(uint32_t slots, Time now) {
    if (!slots || (slots & ~valid_slots_) || (slots & reserved_)) return std::nullopt;
    const auto primary = static_cast<uint16_t>(std::countr_zero(slots));
    const auto lease = credentials_.issue(primary, now);
    if (!lease) return std::nullopt;
    groups_[primary] = slots;
    reserved_ |= slots;
    return NativeRecoveryGroupGrant{*lease, slots};
  }
  std::optional<NativeRecoveryGroupGrant> begin(uint16_t primary,
      const NativeRecoveryMatchId& match, const NativeRecoverySecret& secret, Time now) {
    if (!members(primary)) return std::nullopt;
    const auto lease = credentials_.begin(primary, match, secret, now);
    if (!lease) return std::nullopt;
    return NativeRecoveryGroupGrant{*lease, groups_[primary]};
  }
  bool release_admission(uint16_t primary, uint64_t generation, Time now) {
    if (!members(primary) || !credentials_.release_admission(primary, generation, now)) return false;
    reserved_ &= ~groups_[primary];
    groups_[primary] = 0;
    return true;
  }
  bool detach(uint16_t primary, uint64_t generation, Time now) {
    return members(primary) && credentials_.detach(primary, generation, now);
  }
  bool commit(uint16_t primary, uint64_t generation, const NativeRecoverySecret& secret, Time now) {
    return members(primary) && credentials_.commit(primary, generation, secret, now);
  }
  bool owns(uint16_t primary, uint64_t generation, Time now) {
    return members(primary) && credentials_.owns(primary, generation, now);
  }
  bool attached(uint16_t primary, uint64_t generation, Time now) {
    return members(primary) && credentials_.attached(primary, generation, now);
  }
  bool owns_slot(uint16_t primary, uint64_t generation, uint16_t slot, Time now) {
    return slot < NativeRecoveryCredentials::kMaxSlots &&
        (members(primary) & (uint32_t{1} << slot)) && owns(primary, generation, now);
  }
  bool revoke(uint16_t primary, uint64_t generation, Time now) {
    return members(primary) && credentials_.revoke(primary, generation, now);
  }
  // Membership is not proof of a live lease: expired in-play groups remain
  // reserved for their AI controllers. Only owns/attached grant player control.
  uint32_t members(uint16_t primary) const {
    return primary < groups_.size() ? groups_[primary] : 0;
  }
  uint32_t reserved() const { return reserved_; }
 private:
  NativeRecoveryCredentials credentials_;
  const uint32_t valid_slots_;
  std::array<uint32_t, NativeRecoveryCredentials::kMaxSlots> groups_{};
  uint32_t reserved_ = 0;
};
} // namespace frame_sync
