// 2026-09-14: Native replay checkpoints describe real gaps; no invented authority inputs.
#pragma once
#include "frame_sync/native_match_replay.hpp"
#include "frame_sync/native_recovery_transfer.hpp"
#include <array>
#include <optional>
#include <string_view>
#include <vector>
namespace frame_sync {
inline constexpr size_t kNativeReplayCheckpoints = 32;
inline constexpr size_t kNativeReplaySnapshotBudget = 8 * 1024 * 1024;
inline constexpr size_t kNativeReplayCheckpointHeader = 52;
struct NativeReplayCheckpoint {
  uint32_t record_index = 0, next_frame = 0;
  uint64_t state_hash = 0;
  NativeRecoveryDigest digest{};
  std::vector<uint8_t> state;
  NativeReplayCheckpoint() = default;
  ~NativeReplayCheckpoint() = default;
  NativeReplayCheckpoint(const NativeReplayCheckpoint&) = delete;
  NativeReplayCheckpoint& operator=(const NativeReplayCheckpoint&) = delete;
  NativeReplayCheckpoint(NativeReplayCheckpoint&&) noexcept = default;
  NativeReplayCheckpoint& operator=(NativeReplayCheckpoint&&) noexcept = default;
};
class NativeRecoveryJournal {
 public:
  NativeRecoveryJournal() = delete;
  explicit NativeRecoveryJournal(NativeMatchContract contract,
      ReplayBudget budget = ReplayBudget{}, size_t snapshot_budget = kNativeReplaySnapshotBudget)
      : contract_(contract), recorder_(budget), snapshot_budget_(snapshot_budget) {
    contract_.Validate();
    if (budget.frame_limit > ReplayBudget{}.frame_limit ||
        budget.byte_limit > ReplayBudget{}.byte_limit || !snapshot_budget ||
        snapshot_budget > kNativeReplaySnapshotBudget)
      throw std::invalid_argument("Invalid native checkpoint replay budget");
    recorder_.StartRecording(contract.seed, "default_11v11", contract.left + contract.right);
  }
  ~NativeRecoveryJournal() = default;
  NativeRecoveryJournal(const NativeRecoveryJournal&) = delete;
  NativeRecoveryJournal& operator=(const NativeRecoveryJournal&) = delete;
  NativeRecoveryJournal(NativeRecoveryJournal&&) = delete;
  NativeRecoveryJournal& operator=(NativeRecoveryJournal&&) = delete;
  bool RecordFrame(uint32_t frame, uint64_t hash, const std::vector<SlotInput>& inputs) {
    if (!IsRecording()) return false;
    if (frame != next_frame_ || frame == UINT32_MAX) return refuse(ReplayStopReason::InvalidInput);
    if (!recorder_.RecordFrame(frame, hash, inputs)) return false;
    ++next_frame_;cursor_hash_ = hash;
    return true;
  }
  bool Checkpoint(const NativeRecoverySnapshot& metadata, std::vector<uint8_t> state) {
    if (!IsRecording()) return false;
    if (!valid_recovery_snapshot(metadata) || metadata.size != state.size() ||
        state.capacity() > kNativeRecoverySnapshotBytes || metadata.next_frame < next_frame_ ||
        (metadata.next_frame == next_frame_ && cursor_hash_ && metadata.state_hash != *cursor_hash_))
      return refuse(ReplayStopReason::InvalidInput);
    if (checkpoint_count_ == checkpoints_.size() ||
        state.capacity() > snapshot_budget_ - retained_snapshots_)
      return refuse(ReplayStopReason::Capacity);
    const auto digest = recovery_snapshot_digest(state);
    if (!digest || !native_secret_equal(*digest, metadata.digest)) return refuse(ReplayStopReason::InvalidInput);
    auto& entry = checkpoints_[checkpoint_count_];
    entry.emplace();
    entry->record_index = static_cast<uint32_t>(GetFrameCount());
    entry->next_frame = metadata.next_frame;
    entry->state_hash = metadata.state_hash;
    entry->digest = metadata.digest;
    entry->state.swap(state);
    retained_snapshots_ += entry->state.capacity();
    serialized_snapshots_ += entry->state.size();
    ++checkpoint_count_;
    next_frame_ = metadata.next_frame;cursor_hash_ = metadata.state_hash;
    return true;
  }
  bool IsRecording() const { return reason_ == ReplayStopReason::None && recorder_.IsRecording(); }
  void StopRecording() {
    if (IsRecording()) reason_ = ReplayStopReason::User;
    recorder_.StopRecording();
  }
  ReplayStopReason GetStopReason() const {
    return reason_ == ReplayStopReason::None ? recorder_.GetStopReason() : reason_;
  }
  bool HasReplayContent() const { return GetFrameCount() || checkpoint_count_; }
  size_t GetFrameCount() const { return recorder_.GetFrameCount(); }
  const ReplayMetadata& GetMetadata() const { return recorder_.GetMetadata(); }
  const NativeMatchContract& contract() const { return contract_; }
  uint32_t next_frame() const { return next_frame_; }
  size_t checkpoint_count() const { return checkpoint_count_; }
  const NativeReplayCheckpoint* checkpoint(size_t index) const {
    return index < checkpoint_count_ ? &*checkpoints_[index] : nullptr;
  }
  size_t GetRetainedBytes() const {
    return sizeof(checkpoints_) + recorder_.GetRetainedBytes() + retained_snapshots_;
  }
  size_t GetSerializedBytes() const {
    return checkpoint_count_ ? 44 + kNativeReplayCheckpointHeader * checkpoint_count_ +
        serialized_snapshots_ + recorder_.GetSerializedBytes() :
        NativeReplayView(recorder_, contract_).GetSerializedBytes();
  }
  template<class Sink> size_t SerializeTo(Sink&& sink) const {
    if (!checkpoint_count_) return NativeReplayView(recorder_, contract_).SerializeTo(std::forward<Sink>(sink));
    std::array<uint8_t, 44> header{};
    std::copy_n("FNRPLY2", 8, header.begin());
    const auto descriptor = contract_.Packet();
    std::copy(descriptor.begin(), descriptor.end(), header.begin() + 8);
    native_recovery_wire::put(header, 40, checkpoint_count_, 4);
    auto output = [&](std::span<const uint8_t> bytes) {
      sink(std::string_view(reinterpret_cast<const char*>(bytes.data()), bytes.size()));
    };
    output(header);
    for (size_t n = 0; n < checkpoint_count_; ++n) {
      const auto& entry = *checkpoints_[n];
      std::array<uint8_t, kNativeReplayCheckpointHeader> encoded{};
      native_recovery_wire::put(encoded, 0, entry.record_index, 4);
      native_recovery_wire::put(encoded, 4, entry.next_frame, 4);
      native_recovery_wire::put(encoded, 8, entry.state.size(), 4);
      native_recovery_wire::put(encoded, 12, entry.state_hash, 8);
      std::copy(entry.digest.begin(), entry.digest.end(), encoded.begin()+20);
      output(encoded);output(entry.state);
    }
    const auto written = recorder_.SerializeTo(std::forward<Sink>(sink));
    return 44 + checkpoint_count_ * kNativeReplayCheckpointHeader + serialized_snapshots_ + written;
  }
 private:
  bool refuse(ReplayStopReason reason) { reason_ = reason;recorder_.StopRecording();return false; }
  NativeMatchContract contract_;
  ReplayRecorder recorder_;
  const size_t snapshot_budget_;
  std::array<std::optional<NativeReplayCheckpoint>, kNativeReplayCheckpoints> checkpoints_;
  size_t checkpoint_count_ = 0, retained_snapshots_ = 0, serialized_snapshots_ = 0;
  uint32_t next_frame_ = 0;
  std::optional<uint64_t> cursor_hash_;
  ReplayStopReason reason_ = ReplayStopReason::None;
};

class NativeRecoveryReplayPlayer {
 public:
  NativeRecoveryReplayPlayer() = default;
  ~NativeRecoveryReplayPlayer() = default;
  NativeRecoveryReplayPlayer(const NativeRecoveryReplayPlayer&) = delete;
  NativeRecoveryReplayPlayer& operator=(const NativeRecoveryReplayPlayer&) = delete;
  NativeRecoveryReplayPlayer(NativeRecoveryReplayPlayer&&) = default;
  NativeRecoveryReplayPlayer& operator=(NativeRecoveryReplayPlayer&&) = default;
  bool LoadReplay(std::string_view data) {
    NativeRecoveryReplayPlayer candidate;
    if (!candidate.load(data)) return false;
    *this = std::move(candidate);
    return true;
  }
  const NativeMatchContract& contract() const { return contract_; }
  size_t GetTotalFrames() const { return frames_.GetTotalFrames(); }
  const ReplayMetadata& GetMetadata() const { return frames_.GetMetadata(); }
  auto GetFrameAt(size_t index) const { return frames_.GetFrameAt(index); }
  size_t checkpoint_count() const { return checkpoint_count_; }
  const NativeReplayCheckpoint* checkpoint(size_t index) const {
    return index < checkpoint_count_ ? &*checkpoints_[index] : nullptr;
  }
  uint32_t next_frame() const { return next_frame_; }
  std::optional<uint64_t> final_state_hash() const { return cursor_hash_; }
  size_t snapshot_bytes() const { return snapshot_bytes_; }
 private:
  bool load(std::string_view data) {
    const auto maximum = 44 + kNativeReplayCheckpointHeader * kNativeReplayCheckpoints +
        kNativeReplaySnapshotBudget + ReplayBudget{}.byte_limit;
    if (data.size() < 40 || data.size() > maximum) return false;
    const bool v2 = data.substr(0,8) == std::string_view("FNRPLY2",8);
    if (!v2 && data.substr(0,8) != std::string_view("FNRPLY1",8)) return false;
    const std::span<const uint8_t> bytes(reinterpret_cast<const uint8_t*>(data.data()),data.size());
    if (!NativeMatchContract::Decode(bytes.subspan(8,32), NativeMatchContract::kSession, contract_))
      return false;
    size_t at = 40;
    if (v2) {
      if (data.size() < 44) return false;
      checkpoint_count_ = native_recovery_wire::get(bytes,40,4);
      if (!checkpoint_count_ || checkpoint_count_ > checkpoints_.size()) return false;
      at = 44;
      uint32_t previous_index = 0;
      for (size_t n = 0; n < checkpoint_count_; ++n) {
        if (bytes.size()-at < kNativeReplayCheckpointHeader) return false;
        auto& entry = checkpoints_[n];entry.emplace();
        entry->record_index = native_recovery_wire::get(bytes,at,4);
        entry->next_frame = native_recovery_wire::get(bytes,at+4,4);
        const size_t size = native_recovery_wire::get(bytes,at+8,4);
        entry->state_hash = native_recovery_wire::get(bytes,at+12,8);
        std::copy_n(bytes.begin()+at+20,32,entry->digest.begin());
        at += kNativeReplayCheckpointHeader;
        if (entry->record_index < previous_index || entry->record_index > ReplayBudget{}.frame_limit ||
            entry->next_frame == UINT32_MAX || !size || size > kNativeRecoverySnapshotBytes ||
            size > bytes.size()-at || size > kNativeReplaySnapshotBudget-snapshot_bytes_) return false;
        const auto state = bytes.subspan(at,size);
        const auto digest = recovery_snapshot_digest(state);
        if (!digest || !native_secret_equal(*digest,entry->digest)) return false;
        entry->state.assign(state.begin(),state.end());
        if (entry->state.capacity() > kNativeRecoverySnapshotBytes ||
            entry->state.capacity() > kNativeReplaySnapshotBudget-snapshot_bytes_) return false;
        snapshot_bytes_ += entry->state.capacity();
        previous_index = entry->record_index;
        at += size;
      }
    }
    if (data.size()-at > ReplayBudget{}.byte_limit || !frames_.LoadReplay(std::string(data.substr(at))))
      return false;
    const auto& metadata = frames_.GetMetadata();
    if (metadata.seed != contract_.seed || metadata.num_slots != contract_.left+contract_.right ||
        metadata.scenario != "default_11v11") return false;
    size_t checkpoint = 0;
    for (size_t i = 0; i <= frames_.GetTotalFrames(); ++i) {
      while (checkpoint < checkpoint_count_ && checkpoints_[checkpoint]->record_index == i) {
        const auto& entry = *checkpoints_[checkpoint++];
        if (entry.next_frame < next_frame_ ||
            (entry.next_frame == next_frame_ && cursor_hash_ && entry.state_hash != *cursor_hash_))
          return false;
        next_frame_ = entry.next_frame;cursor_hash_ = entry.state_hash;
      }
      if (i == frames_.GetTotalFrames()) break;
      const auto frame = frames_.GetFrameAt(i);
      if (!frame || frame->frame_number != next_frame_ || next_frame_ == UINT32_MAX) return false;
      ++next_frame_;cursor_hash_ = frame->state_hash;
    }
    return checkpoint == checkpoint_count_;
  }
  NativeMatchContract contract_;
  ReplayPlayer frames_;
  std::array<std::optional<NativeReplayCheckpoint>,kNativeReplayCheckpoints> checkpoints_;
  size_t checkpoint_count_ = 0, snapshot_bytes_ = 0;
  uint32_t next_frame_ = 0;
  std::optional<uint64_t> cursor_hash_;
};
}  // namespace frame_sync
